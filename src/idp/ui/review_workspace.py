"""Shared review and department operations with persisted revision-bound actions."""
import json
import math
import hashlib

import streamlit as st

from idp.review.service import ReviewService, TEAMS, EDITABLE, ReviewConflict, UnsafeApproval
from idp.storage.operations import OperationsQueries
from idp.agents.validation_agent import ValidationAgent


def workspace(repository, *, department=False):
    from idp.ui.console import filters_ui, record_table, document_detail, friendly
    from idp.ui.batches import retained_details
    service = ReviewService(repository)
    st.warning('Trusted local prototype: typed operator identifiers are not authenticated. Team assignment and queue filters do not enforce authorization. Decisions never execute payments or legal agreements.')
    operator = st.text_input('Prototype operator identifier (unauthenticated)',key='review_operator',max_chars=120)
    team = st.selectbox('Team',TEAMS[:4],key='workspace_department') if department else ''
    if department:
        messages = {'Finance':'Invoice reconciliation, amount and supplier issues.',
            'Procurement':'Assigned PO/vendor work and invoices with unresolved PO references.',
            'Expense Processing':'Receipt evidence, arithmetic and high-value cases.',
            'Legal':'Contract parties, dates and unsupported structures.'}
        st.info(messages[team])
    prefix='department_review' if department else 'review'
    selection = filters_ui(OperationsQueries(repository),prefix,search=True)
    a,b,c = st.columns(3)
    risk = a.selectbox('Risk',['','high','medium','low'],format_func=lambda value:friendly(value) if value else 'All risks',key=prefix+'_risk')
    case_status = b.selectbox('Case status',['','open','in_review','on_hold','awaiting_correction','escalated','approved','rejected'],format_func=lambda value:friendly(value) if value else 'All case statuses',key=prefix+'_case_status')
    owner = c.text_input('Assigned operator',key=prefix+'_assignee')
    show_closed = st.checkbox('Include approved and rejected cases',key=prefix+'_closed')
    rows,total=service.queue(selection,team=team,risk=risk,case_status=case_status,assignee=owner,include_closed=show_closed)
    if st.session_state.get(prefix+'_page',1)>max(1,math.ceil(total/20)):
        st.session_state[prefix+'_page']=1
    page = st.number_input('Queue page',min_value=1,max_value=max(1,math.ceil(total/20)),value=1,step=1,key=prefix+'_page')
    rows,total=service.queue(selection,team=team,risk=risk,case_status=case_status,assignee=owner,page=int(page),include_closed=show_closed)
    st.caption(f'{total} cases · received age in days, not review turnaround · priority, risk and oldest received first')
    record_table([{**row,'age_days':round(row['age_days'],1) if row['age_days'] is not None else 'Unavailable'} for row in rows])
    if not rows:
        st.info('No cases match the queue. Adjust filters or include completed decisions.')
        return
    by_id={row['id']:row for row in rows}
    selected=st.selectbox('Select Document for Review',list(by_id),format_func=lambda key:f"{key} · {by_id[key]['filename']}",key='review_document_id' if not department else 'department_document_id')
    document=repository.get_document(selected)
    case=service.case(selected)
    revision=document['revision']
    previous=st.session_state.get(prefix+'_seen_'+str(selected))
    notice=st.session_state.pop('review_notice',None)
    if previous is not None and previous!=revision and not notice:
        st.warning('This record changed since your last view. Inspect the refreshed fields and reconfirm your action.')
    st.session_state[prefix+'_seen_'+str(selected)]=revision
    stamp=f'{prefix}_{selected}_{revision}'
    st.caption(f"Processing version {document['processing_version_id']} · revision {revision} · team {case['team']} · assigned to {case['assignee'] or 'unclaimed'} · {friendly(case['case_status'])}")
    if notice:
        st.success('Action saved with a traceable event. Current revision has been refreshed.')
    left,right=st.columns([1,1.15])
    with left:
        st.subheader('Original source and history')
        retained_details(repository,selected,record_table,expanded=True)
        with repository.connect() as db:
            versions=[dict(row) for row in db.execute('SELECT * FROM processing_versions WHERE document_id=? ORDER BY id DESC',(selected,))]
        with st.expander('Preserved processing originals'):
            version=st.selectbox('Original processing version',[row['id'] for row in versions],key=stamp+'_version')
            row=next(row for row in versions if row['id']==version)
            st.caption(f"{row['origin']} · captured {row['captured_at']}. A legacy current snapshot does not reconstruct earlier history.")
            st.json(json.loads(row['original_state']))
        with st.expander('Decision and case event history',expanded=True):
            events=service.history(selected)
            if not events:
                st.info('No events have been recorded since review migration. Legacy decision history is unavailable.')
            else:
                record_table([{key:event[key] for key in ('id','event_type','actor','created_at','decision','reason','previous_revision','new_revision')} for event in events])
                event=st.selectbox('Inspect event',[event['id'] for event in events],key=stamp+'_event')
                with st.expander('Advanced event details'):
                    st.json(next(value for value in events if value['id']==event))
                st.caption('Rule versions are unavailable: checks are current code rules, not a versioned rule service.')
    with right:
        document_detail(repository,document,prefix,run_id=revision)
        state=document['full_result']
        if not state.get('field_evidence') or state.get('evidence_warnings') or state.get('validation_warnings'):
            st.warning('Some evidence is missing or unverifiable. Approval remains blocked until the checks pass.')
        with st.expander('Correct extracted fields'):
            st.caption('Changes require original OCR evidence. Values unsupported by OCR may be saved for correction, but cannot be approved. Original model output remains preserved. No Groq request is made.')
            kind=state.get('document_type')
            fields=state.get('extracted_fields',{})
            names=sorted(set(fields)|set(ValidationAgent.REQUIRED_FIELDS.get(kind,[]))|set(ValidationAgent.OPTIONAL_FIELDS.get(kind,[])))
            names=[name for name in names if name in EDITABLE]
            changes,evidence={},{}
            for name in names:
                changes[name]=st.text_input(f'{friendly(name)} — corrected value',value=str(fields.get(name) or ''),key=stamp+'_field_'+name)
                evidence[name]=st.text_area(f'{friendly(name)} — OCR evidence quote',value=str(state.get('field_evidence',{}).get(name) or ''),height=75,key=stamp+'_evidence_'+name)
            correction_reason=st.text_area('Correction reason',key=stamp+'_correction_reason')
            fingerprint=hashlib.sha256(json.dumps([changes,evidence],sort_keys=True).encode()).hexdigest()
            if st.button('Preview deterministic checks',key=stamp+'_preview'):
                try:
                    result=service.preview_correction(selected,changes,evidence)
                    st.session_state[stamp+'_preview_result']={'fingerprint':fingerprint,'result':result}
                except ValueError as error:
                    st.error(str(error))
            preview=st.session_state.get(stamp+'_preview_result')
            ready=bool(preview and preview['fingerprint']==fingerprint)
            if ready:
                st.json(service.validation_summary(preview['result']['state']))
            confirmation=st.checkbox('I confirm these corrections and their recorded reason.',key=stamp+'_correct_confirm')
            if st.button('Save corrections',disabled=not ready or not confirmation,key=stamp+'_save_correction'):
                mutate(lambda:service.apply_correction(selected,revision,changes,evidence,actor=operator,reason=correction_reason))
        st.markdown('#### Record a review decision')
        decision=st.selectbox('Review Decision',['approved','rejected','needs_correction','escalated'],format_func=friendly,key=f'review_decision_select_{selected}')
        reason=st.text_area('Decision reason',key=stamp+'_decision_reason')
        notes=st.text_area('Review Notes',key=f'review_notes_{selected}',placeholder='Document-specific notes; a decision reason is required.')
        st.caption('Approval requires fresh mandatory, evidence, PO and risk checks. High confidence never overrides these checks.')
        confirmed=st.checkbox('I confirm this review decision and its reason.',key=stamp+'_decision_confirm')
        if st.button('Save Review Decision',type='primary',disabled=not confirmed,key=stamp+'_decision'):
            mutate(lambda:service.decide(selected,revision,decision,actor=operator,reason=reason,notes=notes))
        with st.expander('Claim, assign and update case'):
            management_reason=st.text_area('Case action reason',key=stamp+'_manage_reason')
            if st.button('Claim case',key=stamp+'_claim'):
                mutate(lambda:service.manage(selected,revision,'claim',actor=operator,reason=management_reason))
            assignment=st.selectbox('Assigned team',TEAMS,index=TEAMS.index(case['team']) if case['team'] in TEAMS else 0,key=stamp+'_team')
            assignee=st.text_input('Assign to prototype operator',value=case['assignee'] or '',key=stamp+'_new_assignee',max_chars=120)
            consent=st.checkbox('I confirm reassignment to this team and operator.',key=stamp+'_assign_confirm')
            if st.button('Assign / reassign case',disabled=not consent,key=stamp+'_assign'):
                mutate(lambda:service.manage(selected,revision,'assign',actor=operator,reason=management_reason,team=assignment,assignee=assignee))
            statuses=['open','in_review','on_hold']
            status=st.selectbox('Working status',statuses,index=statuses.index(case['case_status']) if case['case_status'] in statuses else 0,format_func=friendly,key=stamp+'_status')
            if st.button('Update working status',key=stamp+'_set_status'):
                mutate(lambda:service.manage(selected,revision,'status',actor=operator,reason=management_reason,status=status))
            priorities=['normal','high','urgent']
            priority=st.selectbox('Review priority',priorities,index=priorities.index(case['priority']) if case['priority'] in priorities else 0,format_func=friendly,key=stamp+'_priority')
            if st.button('Set review priority',key=stamp+'_set_priority'):
                mutate(lambda:service.manage(selected,revision,'priority',actor=operator,reason=management_reason,priority=priority))


def mutate(action):
    try:
        action()
    except (ValueError,ReviewConflict,UnsafeApproval) as error:
        st.error(str(error))
        st.info('Refresh the queue if another operator or processing run changed the record.')
    except Exception:
        st.error('The action could not be saved. No partial decision was committed. Refresh and retry.')
    else:
        st.session_state['review_notice']=True
        st.rerun()

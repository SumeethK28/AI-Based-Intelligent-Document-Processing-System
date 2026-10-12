"""Trusted-local policy workspace: immutable drafts, full preview and activation."""
import json
import streamlit as st
from idp.policy.service import PolicyService
from idp.policy.schema import DESCRIPTION


def workspace(repository):
    from idp.ui.console import record_table
    service=PolicyService(repository)
    active=service.active()
    st.warning('Trusted-local administration only. Typed operator names do not provide authentication or authorization. Protect access to this computer. Policy changes never authorize payments or agreements.')
    st.caption(f"Active policy {active['id']} · activation generation {active['generation']}. Existing documents keep their recorded policy until explicit reevaluation.")
    record_table([{'category':key,'value':json.dumps(value),'description':DESCRIPTION[key],'status':'Active','version':active['id']} for key,value in active['config'].items()])
    st.info('Protected safety: OCR evidence, required base fields, supported contract structure, unique PO matching, supplier/currency consistency and non-low risk cannot be bypassed. PO tolerance is bounded to 1 nominal unit; arithmetic tolerance to 0.02.')
    actor=st.text_input('Prototype policy operator (unauthenticated)',key='policy_actor',max_chars=120)
    reason=st.text_area('Policy change reason',key='policy_reason')
    st.subheader('Create a draft')
    st.caption('Edit the categories below as JSON. Unsupported or conflicting settings are rejected. Each saved draft is immutable; create a new draft to revise it.')
    edited={}
    for key,value in active['config'].items():
        edited[key]=st.text_area(key.replace('_',' ').title(),value=json.dumps(value,indent=2),help=DESCRIPTION[key],key=f'policy_edit_{active["generation"]}_{key}',height=120 if isinstance(value,dict) else 75)
    if st.button('Validate and save draft',key='policy_save'):
        try:
            draft=service.draft({key:json.loads(value) for key,value in edited.items()},actor=actor,reason=reason)
            st.success(f'Draft {draft} saved. Preview it below before activation.')
        except (ValueError,TypeError) as error:
            st.error(str(error))
    versions=service.versions()
    statuses={row['id']:row['status'] for row in versions}
    selected=st.selectbox('Draft or historical policy to preview',[row['id'] for row in versions],format_func=lambda value:f"Policy {value} ({statuses[value]})",key='policy_selected')
    proposed=service.version(selected)
    st.caption(f"Selected policy {selected} · {statuses[selected]} · saved by {proposed['actor']} · {proposed['reason']}")
    record_table([{'category':key,'active_value':json.dumps(active['config'][key]),'proposed_value':json.dumps(value),'description':DESCRIPTION[key]} for key,value in proposed['config'].items() if value!=active['config'][key]])
    with st.expander('Selected policy configuration'):
        st.json(proposed['config'])
    st.caption('A historical policy can be reactivated as a rollback after a fresh preview. Previous activations and document history remain intact.')
    if st.button('Preview against all stored documents',key='policy_preview'):
        try:
            st.session_state['policy_preview_result']=service.preview(selected)
        except ValueError as error:
            st.error(str(error))
    preview=st.session_state.get('policy_preview_result')
    ready=preview and preview['version_id']==selected and preview['generation']==active['generation']
    if ready:
        st.subheader('Expected effects — preview only')
        record_table([{key:value for key,value in row.items() if key!='rule_outcomes'} for row in preview['documents']])
        st.caption('Proposed deterministic checks do not alter records or override human restrictions. Explicit reevaluation always returns a record to human review.')
        with st.expander('Preview rule explanations'):
            st.json(preview['documents'])
    confirmation_key=f"policy_confirm_{selected}_{active['generation']}_{preview['id'] if ready else 'unpreviewed'}"
    confirmed=st.checkbox('I confirm activation for future processing after inspecting the preview.',key=confirmation_key)
    if st.button('Activate policy',disabled=not ready or not confirmed,key='policy_activate'):
        try:
            service.activate(selected,preview['id'],actor=actor,reason=reason,confirmed=confirmed)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.pop('policy_preview_result',None)
            st.rerun()
    st.subheader('Policy activation history')
    record_table(service.history())
    st.download_button('Download active policy JSON',json.dumps(active,indent=2),file_name='active_policy.json',mime='application/json')


def explanations(state):
    from idp.ui.console import record_table
    st.markdown('#### Decision explanations')
    version=state.get('policy_version_id')
    st.caption(f'Policy version: {version}' if version is not None else 'Legacy baseline result: no historical policy version was recorded.')
    checks=state.get('rule_outcomes',[])
    if checks:
        record_table(checks)
    else:
        st.caption('Individual policy outcomes were not captured for this legacy result. They will be recorded on new processing or explicit reevaluation.')
    st.write(state.get('routing_reason','Routing explanation unavailable.'))
    if state.get('policy_evaluation_error'):
        st.error(state['policy_evaluation_error'])


def reevaluation(repository,document,actor):
    from idp.ui.review_workspace import mutate
    service=PolicyService(repository)
    active=service.active()
    stamp=f"policy_recheck_{document['id']}_{document['revision']}_{active['generation']}"
    with st.expander('Explicit policy reevaluation'):
        st.caption(f"Recheck under active policy {active['id']}. Earlier outputs and decisions remain in history. This creates an audit event and requires a new human decision; rejection or restrictions are preserved. Rechecking a PO invalidates dependent invoice approvals.")
        reason=st.text_area('Reevaluation reason',key=stamp+'_reason')
        confirmation=st.checkbox('I confirm reevaluation and a new human review.',key=stamp+'_confirm')
        if st.button('Reevaluate under active policy',disabled=not confirmation,key=stamp+'_save'):
            mutate(lambda:service.reevaluate(document['id'],document['revision'],active['id'],actor=actor,reason=reason,confirmed=confirmation))

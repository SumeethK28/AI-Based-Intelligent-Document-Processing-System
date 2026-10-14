"""Trusted-local policy workspace: immutable drafts, full preview and activation."""
import json
import streamlit as st
from idp.policy.service import PolicyService
from idp.policy.schema import DESCRIPTION


def workspace(repository):
    from idp.ui.console import record_table
    service=PolicyService(repository)
    repository.require('policy')
    active=service.active()
    st.info('Administrator access is enforced on the server. Policy changes never authorize payments or agreements. Historical prototype operator names remain unauthenticated.')
    st.caption(f"Active policy {active['id']} · activation generation {active['generation']}. Existing documents keep their recorded policy until explicit reevaluation.")
    record_table([{'category':key,'value':json.dumps(value),'description':DESCRIPTION[key],'status':'Active','version':active['id']} for key,value in active['config'].items()])
    st.info('Protected safety: OCR evidence, required base fields, supported contract structure, unique PO matching, supplier/currency consistency and non-low risk cannot be bypassed. PO tolerance is bounded to 1 nominal unit; arithmetic tolerance to 0.02.')
    actor=st.text_input('Prototype policy operator (unauthenticated)',key='policy_actor',max_chars=120) if repository.internal else repository.access.actor(None,'policy')
    reason=st.text_area('Policy change reason',key='policy_reason')
    st.subheader('Create a draft')
    st.caption('Unsupported or conflicting settings are rejected. Each saved draft is immutable; create a new draft to revise it.')
    edited={}
    if repository.internal:
        for key,value in active['config'].items():
            edited[key]=st.text_area(key.replace('_',' ').title(),value=json.dumps(value,indent=2),help=DESCRIPTION[key],key=f'policy_edit_{active["generation"]}_{key}',height=120 if isinstance(value,dict) else 75)
    else:
        edited={key:json.dumps(value) for key,value in guided_config(active).items()}
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
    with st.expander('Advanced policy JSON (read-only)'): st.json(active)


def guided_config(active):
    import copy
    from idp.agents.validation_agent import ValidationAgent
    from idp.review.service import TEAMS
    config=copy.deepcopy(active['config'])
    stamp=str(active['generation'])
    st.caption('Guided business controls. Protected fields and safety checks cannot be removed. Advanced JSON is available for inspection below.')
    for kind,base in ValidationAgent.REQUIRED_FIELDS.items():
        extra=[value for value in ValidationAgent.OPTIONAL_FIELDS[kind] if value not in base]
        chosen=st.multiselect(kind.replace('_',' ').title()+' — additional mandatory fields',extra,default=[value for value in config['mandatory_fields'][kind] if value in extra],key=stamp+'_required_'+kind)
        config['mandatory_fields'][kind]=list(base)+chosen
        config['departments'][kind]=st.selectbox(kind.replace('_',' ').title()+' — processing department',TEAMS[:4],index=TEAMS[:4].index(config['departments'][kind]),key=stamp+'_routing_'+kind)
    for code,value in config['high_value_thresholds'].items():
        config['high_value_thresholds'][code]=str(st.number_input(code+' high-value review threshold',min_value=.01,max_value=1000000000000.0,value=float(value),key=stamp+'_threshold_'+code))
    added=st.text_input('Additional currency code',max_chars=3,key=stamp+'_currency').strip().upper()
    amount=st.number_input('Additional currency threshold',min_value=.01,value=100000.0,key=stamp+'_currency_threshold')
    if added: config['high_value_thresholds'][added]=str(amount)
    config['unknown_currency_threshold']=str(st.number_input('Unspecified currency review threshold',min_value=.01,max_value=100000.0,value=float(config['unknown_currency_threshold']),key=stamp+'_unknown'))
    config['po_tolerance']=str(st.number_input('Invoice / PO absolute amount tolerance',min_value=0.0,max_value=1.0,value=float(config['po_tolerance']),step=.01,key=stamp+'_po'))
    config['arithmetic_tolerance']=str(st.number_input('Subtotal plus tax tolerance',min_value=0.0,max_value=.02,value=float(config['arithmetic_tolerance']),step=.01,key=stamp+'_arithmetic'))
    for key,label in (('require_po_reference','Require invoice PO references'),('require_contract_expiration','Require contract expiration dates'),('escalate_all','Require additional review for every document')):
        config[key]=st.checkbox(label,value=config[key],key=stamp+'_'+key)
    return config


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

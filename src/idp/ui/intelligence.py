"""Financial and operational intelligence grounded in persisted records."""
import json
import streamlit as st
from idp.storage.intelligence import IntelligenceQueries


def dashboard(queries):
    from idp.ui.presentation import filters_ui,record_table
    selection=filters_ui(queries,'analytics',search=True)
    st.session_state['_analytics_selection']=selection
    data=IntelligenceQueries(queries.repository).report(selection)
    a,b,c=st.columns(3)
    a.metric('Unique documents',data['unique_documents'])
    b.metric('Eligible for departmental processing',data['eligible_documents'])
    c.metric('Manual review workflow',data['manual_review_documents'])
    st.caption('Current preliminary eligibility is not business authorization. Financial values remain separated by currency.')
    area=st.radio('Insight area',['Financial','Operations'],horizontal=True,key='insights_area')
    if area=='Financial':
        financial(data,record_table)
    else:
        operations(data,record_table)
    with st.expander('Definitions, denominators and data limitations'):
        for definition in data['definitions'].values():
            st.write(definition)
        st.write('Single-upload failures before persistence are not measured. No human effort, realized savings, revenue or staffing reductions are inferred.')
    if queries.repository.internal:
        st.download_button('Export analytics (JSON)',json.dumps(data,indent=2),file_name='document_analytics.json',mime='application/json')
    else:
        from idp.ui.security import download_control
        from dataclasses import asdict
        values={key:value.isoformat() if hasattr(value,'isoformat') else value for key,value in asdict(selection).items()}
        download_control(queries.repository,'Export analytics (JSON)','analytics_json',{'filters':values},'secure_analytics')


def financial(data,record_table):
    st.subheader('Financial intelligence')
    currencies=sorted({row['currency'] for group in data['financial'].values() for row in group})
    if currencies:
        currency=st.selectbox('Chart currency',currencies,key='intelligence_currency')
        dimensions={'Invoice eligibility':'currency','Suppliers':'supplier','Received dates':'day','PO verification':'po','High-value exceptions':'high_value'}
        title=st.selectbox('Financial view',list(dimensions),key='financial_dimension')
        for dimension,title in [(dimensions[title],title)]:
            st.markdown('#### '+title)
            rows=[row for row in data['financial'][dimension] if row['currency']==currency]
            with st.expander('Exact values and document counts'):
                record_table(rows)
            st.caption('Extracted invoice value · '+currency+' · not revenue or payments')
            chart=[{'category':row['category'],'invoice_value':float(row['extracted_value'])} for row in rows]
            if chart:
                st.line_chart(chart,x='category',y='invoice_value') if dimension=='day' else st.bar_chart(chart,x='category',y='invoice_value')
    else:
        st.info('No parseable invoice values in this document cohort.')
    st.caption(f"Excluded unparseable invoice totals: {data['unparseable_invoice_totals']}. Missing currencies remain unspecified. Values are extracted invoice amounts, not revenue or payments.")
    with st.expander('Duplicate business identifiers'):
        record_table(data['duplicate_business_groups'])


def operations(data,record_table):
    st.subheader('Operations and automation')
    dimensions={'Document types':'types','Open department workload':'department_backlog','Backlog age':'backlog_age','Validation failures':'validation_patterns','Anomaly patterns':'anomaly_patterns','Rules requiring review':'policy_patterns'}
    title=st.selectbox('Operational view',list(dimensions),key='operational_dimension')
    for key,title in [(dimensions[title],title)]:
        st.markdown('#### '+title)
        if data[key]:
            st.bar_chart([{'category':name,'count':count} for name,count in data[key].items()],x='category',y='count')
            record_table([{'category':name,'documents_or_occurrences':count} for name,count in data[key].items()])
    with st.expander('Corrections, interventions and duplicates'):
        record_table([{key:data[key] for key in ('corrected_documents','correction_events','intervened_documents','correction_rate','intervention_rate','recorded_submissions','duplicate_submissions','duplicate_submission_rate','rejected_documents')}])
    with st.expander('Processing performance'):
        record_table([{'measurement':key,**data[key]} for key in ('processing_time','batch_attempt_time')])
    with st.expander('Batch outcomes and retries'):
        record_table([{key:value for key,value in data['batches'].items() if key!='states'}])
        if data['batches']['states']:
            st.bar_chart(data['batches']['states'])
        st.caption(data['definitions']['batch_cohort'])
        st.caption(data['definitions']['batch_rates'])

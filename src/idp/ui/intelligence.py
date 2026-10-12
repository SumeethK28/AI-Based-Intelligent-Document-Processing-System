"""Financial and operational intelligence grounded in persisted records."""
import json
import streamlit as st
from idp.storage.intelligence import IntelligenceQueries


def dashboard(queries):
    from idp.ui.console import filters_ui,record_table
    data=IntelligenceQueries(queries.repository).report(filters_ui(queries,'analytics',search=True))
    a,b,c=st.columns(3)
    a.metric('Unique documents',data['unique_documents'])
    b.metric('Eligible for departmental processing',data['eligible_documents'])
    c.metric('Manual review workflow',data['manual_review_documents'])
    st.caption('Current preliminary eligibility is not business authorization. Financial values remain separated by currency.')
    st.subheader('Financial intelligence')
    currencies=sorted({row['currency'] for group in data['financial'].values() for row in group})
    if currencies:
        currency=st.selectbox('Chart currency',currencies,key='intelligence_currency')
        for dimension,title in (('currency','Invoice value by eligibility'),('supplier','Supplier invoice value'),('day','Invoice value by received day'),('po','Invoice value by PO verification'),('high_value','High-value invoice exceptions')):
            st.markdown('#### '+title)
            rows=[row for row in data['financial'][dimension] if row['currency']==currency]
            record_table(rows)
            chart=[{'category':row['category'],'invoice_value':float(row['extracted_value'])} for row in rows]
            if chart:
                st.line_chart(chart,x='category',y='invoice_value') if dimension=='day' else st.bar_chart(chart,x='category',y='invoice_value')
    else:
        st.info('No parseable invoice values in this document cohort.')
    st.caption(f"Excluded unparseable invoice totals: {data['unparseable_invoice_totals']}. Missing currencies remain unspecified. Values are extracted invoice amounts, not revenue or payments.")
    st.markdown('#### Duplicate business identifiers')
    record_table(data['duplicate_business_groups'])
    st.subheader('Operations and automation')
    for key,title in (('types','Unique documents by type'),('department_backlog','Open department workload'),('backlog_age','Review backlog age'),('validation_patterns','Validation checks and failures'),('anomaly_patterns','Recorded anomaly patterns'),('policy_patterns','Rules requiring review')):
        st.markdown('#### '+title)
        if data[key]:
            st.bar_chart([{'category':name,'count':count} for name,count in data[key].items()],x='category',y='count')
            record_table([{'category':name,'documents_or_occurrences':count} for name,count in data[key].items()])
    record_table([{key:data[key] for key in ('corrected_documents','correction_events','intervened_documents','correction_rate','intervention_rate','recorded_submissions','duplicate_submissions','duplicate_submission_rate','rejected_documents')}])
    st.markdown('#### Processing time distributions')
    record_table([{'measurement':key,**data[key]} for key in ('processing_time','batch_attempt_time')])
    st.markdown('#### Batch outcomes and retry frequency')
    record_table([{key:value for key,value in data['batches'].items() if key!='states'}])
    if data['batches']['states']:
        st.bar_chart(data['batches']['states'])
    st.caption(data['definitions']['batch_cohort'])
    st.caption(data['definitions']['batch_rates'])
    with st.expander('Definitions, denominators and data limitations',expanded=True):
        for definition in data['definitions'].values():
            st.write(definition)
        st.write('Single-upload failures before persistence are not recorded and cannot be measured. No realized savings, staffing reductions, revenue or historical human effort are inferred.')
    st.download_button('Export analytics (JSON)',json.dumps(data,indent=2),file_name='document_analytics.json',mime='application/json')

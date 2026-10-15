"""Shared Streamlit presentation: static theme, safe text, filters and tables.

No processing, authorization decisions or database mutations live here.
"""
from datetime import date
import streamlit as st
from idp.storage.operations import DocumentFilters
from idp.utils.exports import spreadsheet_safe

CSS = """<style>
:root {--idp-accent:#3b82f6; --idp-border:rgba(128,128,128,.22); --idp-surface:rgba(128,128,128,.055);}
.stMainBlockContainer {max-width:1440px; padding-top:2rem; padding-bottom:3rem;}
[data-testid="stSidebar"] {border-right:1px solid var(--idp-border);}
[data-testid="stSidebar"] [role="radiogroup"] {gap:.45rem;}
[data-testid="stMetric"] {background:var(--idp-surface); padding:1rem 1.15rem;
 border-radius:12px; border:1px solid var(--idp-border); min-width:0;}
[data-testid="stMetricValue"] {font-size:clamp(1.3rem,2vw,1.9rem); font-weight:650;}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] > div,
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {
 white-space:normal !important; overflow-wrap:anywhere; text-overflow:clip; overflow:visible;}
h1 {letter-spacing:-.035em;} h2,h3 {letter-spacing:-.02em;}
h1,h2,h3 {white-space:normal; overflow-wrap:anywhere;}
[data-testid="stText"], [data-testid="stText"] pre {
 font-family:inherit; font-size:1rem; line-height:1.5;
 white-space:pre-wrap; overflow-wrap:anywhere;}
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"] {border-radius:.6rem;}
[data-testid="stExpander"] {border-radius:10px;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius:12px;}
button p {white-space:normal; overflow-wrap:break-word;}
@media(max-width:1200px) {
 [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
 [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
  flex:1 1 14rem !important; min-width:min(100%,14rem) !important; }
 .stMainBlockContainer {padding-left:1.5rem; padding-right:1.5rem;}
}
@media(max-width:760px) {.stMainBlockContainer {padding:1rem .85rem 2rem;}
 [data-testid="stMetric"] {padding:.75rem;} }
</style>"""


def friendly(value):
    labels = {'pending_department_review': 'Awaiting department review',
              'manual_review': 'Needs manual review', 'not_checked': 'No PO reference',
              'not_applicable': 'Not applicable', 'needs_correction': 'Needs correction',
              'po_reference': 'Purchase Order reference', 'tax_id': 'Seller tax ID', 'iban': 'IBAN'}
    return labels.get(value, str(value or "Unavailable").replace("_", " ").capitalize())


def filters_ui(queries, prefix, *, search=False):
    options = queries.options()
    query = st.text_input("Search filename, document number or business party", key=prefix + "_search") if search else ""
    with st.expander("Filter records"):
        a, b, c = st.columns(3)
        kind = a.selectbox("Document type", [""] + options["document_type"], format_func=lambda v: friendly(v) if v else "All types", key=prefix + "_type")
        department = b.selectbox("Department", [""] + options["department"], format_func=lambda v: v or "All departments", key=prefix + "_department")
        status = c.selectbox("Workflow status", [""] + options["status"], format_func=lambda v: friendly(v) if v else "All statuses", key=prefix + "_status")
        use_dates = st.checkbox("Filter by document received date (UTC)", key=prefix + "_dates")
        a, b = st.columns(2)
        start = a.date_input("Received from", value=date.today().replace(day=1), disabled=not use_dates, key=prefix + "_start")
        end = b.date_input("Received through", value=date.today(), disabled=not use_dates, key=prefix + "_end")
        if use_dates and start > end:
            st.warning("Choose a start date on or before the end date.")
            st.stop()
        decision = st.selectbox("Review decision", [""] + options["review_decision"], format_func=lambda v: friendly(v) if v else "All decisions", key=prefix + "_decision")
        currency = ""
        minimum = maximum = None
        batch_id = ""
        if search:
            from idp.batch.service import BatchService
            a,b,c = st.columns(3)
            currency = a.text_input('Currency code',key=prefix+'_currency',max_chars=3).strip().upper()
            use_amount = st.checkbox('Filter by extracted amount',key=prefix+'_money')
            if use_amount:
                st.caption('Amounts are nominal extracted values. Choose a currency to avoid comparing different units.')
            minimum = b.number_input('Minimum amount',value=0.0,disabled=not use_amount,key=prefix+'_min') if use_amount else None
            maximum = c.number_input('Maximum amount',value=1000000.0,disabled=not use_amount,key=prefix+'_max') if use_amount else None
            if minimum is not None and minimum > maximum:
                st.warning('Minimum amount must not exceed maximum amount.')
                st.stop()
            from idp.ui.security import allowed
            jobs = BatchService(queries.repository).history() if allowed(queries.repository,'batches') else []
            names = {job['id']:job['name'] for job in jobs}
            batch_id = st.selectbox('Batch membership',['']+list(names),format_func=lambda key:names.get(key,'All batches'),key=prefix+'_batch')
    return DocumentFilters(kind, department, status, decision, start if use_dates else None, end if use_dates else None, query,currency,minimum,maximum,batch_id)


def record_table(rows):
    if rows:
        st.dataframe([{friendly(k): spreadsheet_safe(friendly(v) if k in {"document_type", "workflow_status", "review_decision", "cross_document_status"} else v)
                       for k, v in row.items()} for row in rows], hide_index=True, width="stretch")


def issues(values):
    for item in values:
        st.warning('Verification needs attention.')
        # Document-derived descriptions must not load Markdown images or links.
        st.text(item.get("description", str(item)) if isinstance(item, dict) else str(item))


def status_summary(state):
    # A single wrapping strip keeps the outcome and safety signals together.
    validation = ('Passed' if state['validation_passed'] else 'Needs attention') if 'validation_passed' in state else 'Not recorded'
    values = (friendly(state.get('workflow_status')), friendly(state.get('cross_document_status')),
              friendly(state.get('risk_level')), validation)
    with st.container(border=True):
        for column, label, value in zip(st.columns(4), ('Workflow', 'PO verification', 'Risk', 'Validation'), values):
            with column:
                st.caption(label)
                st.text(value)


def extracted_information(fields):
    groups = {
        'Document identity': {'invoice_number','po_number','receipt_number','contract_number','contract_title'},
        'Business parties': {'seller','client','vendor','buyer','party_a','party_b','tax_id','iban'},
        'Dates and terms': {'issue_date','order_date','effective_date','expiration_date','payment_method','governing_law','po_reference'},
        'Amounts': {'subtotal','tax','total','contract_value'},
    }
    remaining = dict(fields)
    for title, names in groups.items():
        selected = [(name, value) for name, value in fields.items() if name in names]
        if not selected:
            continue
        with st.container(border=True):
            st.markdown('##### ' + title)
            columns = st.columns(2)
            for index, (name, value) in enumerate(selected):
                with columns[index % 2]:
                    st.caption(friendly(name))
                    st.text(str(value) if value is not None and str(value).strip() else 'Not extracted')
                remaining.pop(name, None)
    if remaining:
        with st.expander('Additional extracted information'):
            record_table([{'field': friendly(k), 'value': v} for k, v in remaining.items()])

"""Business-facing views over the existing processing and storage services."""
import hashlib
import json
import os
from dotenv import load_dotenv
import tempfile
from dataclasses import replace
from datetime import date
from pathlib import Path

import streamlit as st

from idp.storage.operations import DocumentFilters, OperationsQueries
from idp.storage.repository import DocumentRepository
from idp.utils.exports import spreadsheet_safe

PAGES = ("Overview", "Process Documents", "Bulk Processing", "Document Repository", "Review Center", "Department Workspaces",
         "Business Analytics", "Business Rules", "Audit & Settings")
DESCRIPTIONS = {
    "Bulk Processing": "Submit, resume and investigate persistent mixed-document batches.",
    "Overview": "Your operation at a glance. See what needs attention and where work is waiting.",
    "Process Documents": "Extract, verify and route an invoice, purchase order, receipt or contract.",
    "Document Repository": "Find stored information, source evidence and processing history.",
    "Review Center": "Resolve documents awaiting a recorded review decision, with their evidence in view.",
    "Department Workspaces": "Explore routed work by team. Department selection is a filter, not an access restriction.",
    "Business Analytics": "Understand volumes and invoice values using actual stored records.",
    "Business Rules": "Configure, preview and activate versioned document policies with protected safety checks.",
    "Audit & Settings": "Understand data handling and the limits of this local prototype.",
}
CSS = """<style>
.stMainBlockContainer {max-width:1440px; padding-top:2.3rem; padding-bottom:3rem;}
[data-testid="stSidebar"] {border-right:1px solid color-mix(in srgb,currentColor 12%,transparent);}
[data-testid="stMetric"] {background:rgba(128,128,128,.08); padding:1.15rem 1.3rem;
 border-radius:12px; border:1px solid color-mix(in srgb,currentColor 10%,transparent);}
[data-testid="stMetricValue"] {font-size:clamp(1.45rem,2.5vw,2.1rem); font-weight:650;}
h1 {letter-spacing:-.035em;} h2,h3 {letter-spacing:-.02em;}
[data-testid="stExpander"] {border-radius:10px;}
@media(max-width:760px) {.stMainBlockContainer {padding-top:1.2rem;} [data-testid="stMetric"] {padding:.85rem;}}
</style>"""


def friendly(value):
    return str(value or "Unavailable").replace("_", " ").title()


def get_repository(database_path):
    return DocumentRepository(database_path)


def get_pipeline(database_path):
    # Expensive OCR/model initialization happens only when processing starts.
    from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
    return AgenticDocumentPipeline(database_path=database_path,session_token=st.session_state.get('auth_token'))


def navigate(page):
    st.session_state["navigation"] = page


def filters_ui(queries, prefix, *, search=False):
    options = queries.options()
    with st.expander("Filter records", expanded=search):
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
        query = st.text_input("Search filename, document number or business party", key=prefix + "_search") if search else ""
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


def document_detail(repository, document, prefix, *, run_id="latest", duplicate=False):
    repository.access.document(document['id'])
    state = document["full_result"]
    st.subheader(document["filename"])
    st.caption(f"Document {document['id']} · {friendly(state.get('document_type'))} · {state.get('assigned_department', 'Unassigned')}")
    if duplicate:
        st.info("Duplicate submission: saved results reused without a new AI request.")
    for column, label, key in zip(st.columns(3), ("Workflow", "Verification", "Risk policy"), ("workflow_status", "cross_document_status", "risk_level")):
        column.metric(label, friendly(state.get(key)))
    st.write(state.get("routing_reason", "Routing reason unavailable."))
    from idp.ui.policies import explanations
    explanations(state)
    st.caption('Current human decision: ' + friendly(document.get('review_decision','pending')))
    if state.get("validation_passed"):
        st.success("Preliminary field and evidence checks passed. This is not payment or legal authorization.")
    else:
        st.warning("Field checks need attention before normal processing.")
    for key in ("validation_errors", "validation_warnings", "anomalies"):
        issues(state.get(key, []))
    fields = state.get("extracted_fields", {})
    st.markdown("#### Extracted information")
    st.caption("Formula-like text is escaped in table/CSV views. Original values are preserved in JSON.")
    if fields:
        record_table([{"field": friendly(field), "value": value, "source": "Not extracted / omitted" if not value else "Human correction (authenticated account)" if state.get('field_provenance',{}).get(field,{}).get('actor_kind')=='authenticated_user' else "Human correction (historical prototype operator)" if state.get('field_provenance',{}).get(field,{}).get('source')=='human_correction' else "Verified OCR/layout fallback" if field in state.get("fallback_used", []) else "AI extraction"} for field, value in fields.items()])
    else:
        st.info("No structured fields were extracted.")
    with st.expander("Field Evidence"):
        st.json(state.get("field_evidence", {}))
        if state.get('field_provenance'):
            st.json(state['field_provenance'])
        if state.get("contract_parties"):
            st.write("Named contracting parties:", state["contract_parties"])
        issues(state.get("unsupported_contract_reasons", []))
    if state.get("missing_optional_fields"):
        st.caption("Optional information unavailable: " + ", ".join(friendly(f) for f in state["missing_optional_fields"]))
    with st.expander("Purchase order comparison"):
        st.write("Comparison:", friendly(state.get("cross_document_status")))
        issues(state.get("cross_document_issues", []))
        if state.get("matched_document_id"):
            po = repository.get_document(state["matched_document_id"])
            if po:
                st.write("Linked purchase order:", po["filename"])
                st.json(po["extracted_data"])
                def open_linked():
                    st.session_state['linked_document_id'] = po['id']
                    st.session_state['navigation'] = 'Document Repository'
                st.button('Open linked purchase order',key=f'{prefix}_linked_{document["id"]}',on_click=open_linked)
        if state.get("cross_document_status") == "not_checked":
            st.caption("No purchase order reference extracted; no PO comparison performed.")
    with st.expander("Recognized text and processing details"):
        st.text_area("Recognized document text", state.get("ocr_text", ""), height=260, disabled=True, key=f"{prefix}_ocr_{document['id']}_{run_id}")
        st.caption("OCR and classification confidence are reported scores, not measured accuracy.")
        st.json({key: state.get(key) for key in ("ocr_confidence", "classification_confidence", "extraction_confidence", "agent_history")})
    if repository.internal:
        st.download_button('Download Processing Result (JSON)',json.dumps(state),file_name='document.json',key=f'{prefix}_download_{document["id"]}_{run_id}')
    else:
        from idp.ui.security import download_control
        download_control(repository,'Download Processing Result (JSON)','document_json',{'document_id':document['id']},f'{prefix}_download_{document["id"]}')


def overview(queries):
    selection = filters_ui(queries, "overview")
    data = queries.overview(selection)
    metrics = (("Unique documents", "unique_documents"), ("Validated documents", "validated"), ("Review exceptions", "review_exceptions"), ("PO mismatches", "po_mismatches"),
               ("Submissions", "submissions"), ("Cached duplicates", "duplicate_submissions"), ("Awaiting decision", "pending_decisions"), ("Department queue", "department_pending"))
    for group in (metrics[:4], metrics[4:]):
        for column, (label, key) in zip(st.columns(4), group):
            column.metric(label, data[key])
    st.caption("Unique documents count each hash once. Submissions include reprocessing and cached duplicates for the selected document cohort. Awaiting decision includes normal departmental work; review exceptions are escalated cases with a pending decision.")
    for column, label, page in zip(st.columns(3), ("Process a document", "Open review cases", "Browse repository"), ("Process Documents", "Review Center", "Document Repository")):
        from idp.ui.security import allowed,PAGE_PERMISSION
        if allowed(queries.repository,PAGE_PERMISSION[page]): column.button(label, on_click=navigate, args=(page,), width="stretch", type="primary" if page == "Process Documents" else "secondary")
    if not data["unique_documents"]:
        st.info("No documents match this view. Adjust filters or process your first document.")
        return
    left, right = st.columns(2)
    with left:
        st.subheader("Team workload")
        record_table(data["departments"])
    with right:
        st.subheader("Invoice values by currency")
        record_table(data["invoice_values"])
        if not data["invoice_values"]:
            st.caption("No parseable invoice totals in this view.")
        st.caption("Extracted amounts by currency and decision category, not paid balances.")
    st.subheader("Needs attention")
    exception_rows = queries.exceptions(selection) if allowed(queries.repository,'documents') else []
    record_table(exception_rows)
    if not exception_rows:
        st.caption("No pending escalated cases match this view." if allowed(queries.repository,'documents') else 'This role receives summary counts. Individual case details require document access.')
    st.subheader("Recent processing activity")
    record_table(data["activity"])


def process_document(database_path, repository):
    repository.require('process')
    st.info("Document text is sent to the configured Groq service. Use authorized documents only.")
    st.caption("For multiple documents, open Bulk Processing. Single uploads remain temporary; batch sources are retained locally.")
    def clear_result():
        st.session_state.pop("last_result", None)
        st.session_state.pop("last_upload_hash", None)
    upload = st.file_uploader("Choose a document", type=["pdf", "jpg", "jpeg", "png"], key="document_uploader", on_change=clear_result)
    if upload is None:
        st.info("Choose an invoice, purchase order, receipt or contract to begin.")
        return
    if repository.internal and upload.type.startswith("image/"):
        with st.expander("Document preview"):
            st.image(upload, width=500)
    force = st.checkbox("Reprocess even if document already exists", key="force_reprocess", help="Runs OCR and AI again, updates the latest result and resets the review decision. Uses API quota.")
    consent=st.checkbox('I authorize sending this document OCR text to the configured external Groq service.',key='ai_consent')
    if st.button("Process with AI Agents", type="primary", width="stretch",disabled=not consent):
        st.session_state.pop("last_result", None)
        try:
            with st.spinner("Reading, checking and routing your document…"):
                with tempfile.TemporaryDirectory(prefix="idp_upload_") as directory:
                    path = Path(directory) / ("document" + Path(upload.name).suffix.lower())
                    content = upload.getvalue()
                    path.write_bytes(content)
                    result = get_pipeline(database_path).process(path, original_filename=Path(upload.name).name, force_reprocess=force,ai_consent=consent)
                    st.session_state["last_result"] = result
                    st.session_state["last_upload_hash"] = hashlib.sha256(content).hexdigest()
            st.success(result["message"])
        except Exception as error:
            status = getattr(error, "status_code", None)
            st.error("Document processing could not be completed.")
            st.caption("Usage limit reached. Wait before retrying." if status == 429 else
                       "Authentication failed. Check the service configuration." if status in {401, 403} else
                       "Check the document and service availability, then retry.")
    result = st.session_state.get("last_result")
    if result:
        document = repository.get_document(result["document_id"])
        if document:
            document_detail(repository, document, "processing", run_id=result["run_id"], duplicate=result.get("duplicate", False))


def browse(queries, repository, selection, prefix, *, review=False):
    repository.require('documents')
    if not repository.internal and prefix=='repository':
        from idp.ui.security import download_control
        from dataclasses import asdict
        encoded={key:value.isoformat() if hasattr(value,'isoformat') else value for key,value in asdict(selection).items()}
        download_control(repository,'Download filtered JSON','filtered_json',{'filters':encoded},'secure_filtered_json')
        download_control(repository,'Download filtered CSV','filtered_csv',{'filters':encoded},'secure_filtered_csv')
    if repository.internal and prefix == 'repository':
        if st.button('Prepare filtered export'):
            try:
                records = queries.export(selection)
                st.session_state['repository_export'] = {'filter':selection,'records':records}
            except ValueError as error:
                st.warning(str(error))
        export = st.session_state.get('repository_export')
        if export and export['filter']==selection:
            from idp.batch.service import BatchService
            records = export['records']
            st.download_button('Download filtered JSON',json.dumps(records,indent=2),file_name='repository.json',mime='application/json')
            flat = [{**row,'extracted_data':json.dumps(row['extracted_data'])} for row in records]
            st.download_button('Download filtered CSV',BatchService.csv(flat),file_name='repository.csv',mime='text/csv')
        linked = st.session_state.get('linked_document_id')
        if linked:
            document = repository.get_document(linked)
            if document:
                with st.expander('Linked document',expanded=True):
                    document_detail(repository,document,'linked')
            if st.button('Close linked document'):
                st.session_state.pop('linked_document_id',None)
                st.rerun()
    a, b = st.columns(2)
    sort = a.selectbox("Sort records", ["Newest first", "Oldest first", "Filename"], key=prefix + "_sort")
    _, total = queries.page(selection, page_size=1)
    max_page = max(1, (total + 19) // 20)
    page_key = prefix + "_page"
    if st.session_state.get(page_key, 1) > max_page:
        st.session_state[page_key] = 1
    page = b.number_input("Page", min_value=1, max_value=max_page, value=1, step=1, key=page_key)
    rows, total = queries.page(selection, page=int(page), sort=sort)
    st.caption(f"{total} unique documents · page {page} of {max_page} · 20 records per page")
    if not rows:
        st.info("No documents match these filters.")
        return
    record_table(rows)
    by_id = {row["id"]: row for row in rows}
    selected = st.selectbox("Select Document for Review" if review else "Open document", list(by_id),
                            format_func=lambda key: f"{key} · {by_id[key]['filename']}", key="review_document_id" if review else prefix + "_document_id")
    document = repository.get_document(selected)
    if not document:
        st.warning("This record is no longer available. Refresh the view.")
        return
    st.divider()
    document_detail(repository, document, prefix)
    with st.expander('Review and policy audit history (read-only)'):
        from idp.review.service import ReviewService
        audit_events=ReviewService(repository).history(selected)
        record_table([{key:event[key] for key in ('id','event_type','actor','actor_kind','created_at','decision','reason','previous_revision','new_revision')} for event in audit_events])
        if not audit_events:
            st.caption('No review events recorded. Earlier unavailable history is not reconstructed.')
        else:
            event_id=st.selectbox('Inspect audit event',[event['id'] for event in audit_events],key=f'{prefix}_audit_{selected}')
            with st.expander('Recorded audit details'):
                st.json(next(event for event in audit_events if event['id']==event_id))
        st.caption('authenticated_user identifies a verified account; prototype_operator identifies an unauthenticated historical label. This view has no review mutation controls.')
    from idp.ui.batches import retained_details
    retained_details(repository,selected,record_table)
    with st.expander("Recorded processing history"):
        record_table(queries.document_runs(selected))
        st.caption("New runs retain result snapshots. Legacy run snapshots are unavailable. Batch failures and measured durations are in Bulk Processing.")
        with repository._connect() as db:
            runs = [dict(row) for row in db.execute('SELECT id,result_snapshot FROM processing_runs WHERE document_id=? AND result_snapshot IS NOT NULL ORDER BY id DESC',(selected,))]
        if runs:
            run = st.selectbox('Inspect recorded run',[row['id'] for row in runs],key=prefix+'_run')
            st.json(json.loads(next(row['result_snapshot'] for row in runs if row['id']==run)))
    st.caption("Review decision: " + friendly(document["review_decision"]))
    if document.get("review_notes"):
        st.caption('Recorded review notes:')
        st.text(document['review_notes'])


def main():
    load_dotenv()
    st.set_page_config(page_title="Document Operations | Enterprise IDP", page_icon="📄", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)  # Static CSS; never interpolate document content.
    database_path = os.getenv("IDP_DATABASE_PATH", "data/idp.db")
    repository = get_repository(database_path)
    from idp.ui.security import gate,account_controls,allowed,PAGE_PERMISSION
    repository,principal=gate(repository)
    queries = OperationsQueries(repository)
    with st.sidebar:
        st.markdown("## Document Operations")
        st.caption("Enterprise IDP · local prototype")
        pages=[page for page in PAGES if allowed(repository,PAGE_PERMISSION[page])]
        if not repository.internal and allowed(repository,'users'): pages.append('Accounts')
        if st.session_state.get('navigation') not in pages: st.session_state.pop('navigation',None)
        page = st.radio("Workspace", pages, key="navigation", label_visibility="collapsed")
        repository.require(PAGE_PERMISSION[page])
        account_controls(repository,principal)
        st.divider()
        st.caption("Evidence-grounded processing. No payment or legal execution.")
        st.caption('Authenticated local research prototype. Department scope is enforced in services; OS administrator access remains privileged.')
    st.caption("DOCUMENT OPERATIONS / " + page.upper())
    st.title(page)
    st.caption(DESCRIPTIONS.get(page,'Manage individual accounts and explicit department scope.'))
    st.divider()
    if page == "Overview":
        overview(queries)
    elif page == "Process Documents":
        process_document(database_path, repository)
    elif page == 'Bulk Processing':
        from idp.ui.batches import bulk_page
        bulk_page(repository,lambda:get_pipeline(database_path),record_table)
    elif page == "Document Repository":
        browse(queries, repository, filters_ui(queries, "repository", search=True), "repository")
    elif page == "Review Center":
        from idp.ui.review_workspace import workspace
        workspace(repository)
    elif page == "Department Workspaces":
        from idp.ui.review_workspace import workspace
        workspace(repository,department=True)
    elif page == "Business Analytics":
        from idp.ui.intelligence import dashboard
        dashboard(queries)
    elif page == "Business Rules":
        from idp.ui.policies import workspace
        workspace(repository)
    elif page=='Accounts':
        from idp.ui.security import accounts
        accounts(repository)
    else:
        st.subheader("Processing and data handling")
        st.write("OCR runs locally. Document text is sent to Groq. SQLite stores recognized text, fields and current decisions. Single uploads are temporary; batch sources are retained locally and eligible for explicit cleanup after 30 days.")
        st.write("Classification, extraction, validation, anomalies and purchase orders are checked before routing. Confidence values are reported scores, not calibrated accuracy.")
        st.info('Individual accounts and server-side department authorization are enforced. This prototype has no MFA, cryptographic audit protection, encrypted SQLite storage or compliance certification. OS administrators remain privileged.')
        from idp.ui.security import password_form
        password_form(repository)
        st.caption("Configured model: " + os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
        st.caption("Credentials are never displayed. Transient provider retries are bounded; invalid credentials are not repeatedly retried.")
        record_table(queries.overview()["activity"])
        if allowed(repository,'security_audit'):
            with repository._connect() as db:
                events=[dict(row) for row in db.execute('SELECT id,event_type,user_id,outcome,resource,created_at FROM security_events ORDER BY id DESC LIMIT 100')]
            st.subheader('Security event history'); record_table(events)
        if allowed(repository,'governance'):
            from idp.security.governance import GovernanceService
            st.subheader('Retention and source cleanup')
            service=GovernanceService(repository)
            candidates=service.candidates(); record_table(candidates)
            eligible=[row for row in candidates if row['eligible']]
            if eligible:
                selected=st.selectbox('Expired unlinked source',[row['id'] for row in eligible])
                confirmed=st.checkbox('I confirm deletion of this expired source with no document or audit reference.')
                if st.button('Clean up expired source',disabled=not confirmed):
                    try: service.cleanup(selected,confirmed=confirmed)
                    except ValueError as error: st.error(str(error))
                    else: st.success('Expired unlinked source removed; document and audit rows preserved.')

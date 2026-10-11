
import hashlib
import json
import os
import tempfile
from pathlib import Path

import streamlit as st

from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Enterprise Intelligent Document Processing",
    page_icon="📄",
    layout="wide",
)


# ============================================================
# PIPELINE INITIALIZATION
# ============================================================

@st.cache_resource
def get_pipeline():
    return AgenticDocumentPipeline(database_path=os.getenv("IDP_DATABASE_PATH", "data/idp.db"))


pipeline = get_pipeline()
repository = pipeline.repository


# ============================================================
# SESSION STATE
# ============================================================

def clear_processing_result():
    st.session_state.pop("last_result", None)
    st.session_state.pop("last_upload_hash", None)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def format_name(value: str) -> str:
    return str(value).replace("_", " ").title()


def display_issues(issues):
    if not issues:
        st.success("No issues reported.")
        return

    for issue in issues:
        if isinstance(issue, dict):
            severity = issue.get("severity", "unknown")
            code = issue.get("code", "ISSUE")
            description = issue.get("description", "")

            st.warning(
                f"[{severity.upper()}] "
                f"{code}: {description}"
            )
        else:
            st.warning(str(issue))


def show_processing_result(result):

    state = result["state"]

    st.divider()
    st.header("Processing Results")

    # --------------------------------------------------------
    # Processing metadata
    # --------------------------------------------------------

    st.caption(
        f"Document ID: {result['document_id']}  |  "
        f"Processing Run: {result['run_id']}"
    )

    if result.get("duplicate"):
        st.warning(
            "Exact duplicate detected. "
            "Previously stored processing results were reused."
        )

    elif result.get("reprocessed"):
        st.info(
            "This document was reprocessed using the "
            "current AI pipeline."
        )

    # --------------------------------------------------------
    # Summary metrics
    # --------------------------------------------------------

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Document Type",
        format_name(
            state.get("document_type", "unknown")
        ),
    )

    col2.metric(
        "OCR Confidence",
        (
            f"{state.get('ocr_confidence', 0) * 100:.2f}%"
        ),
    )

    col3.metric(
        "Risk Level",
        format_name(
            state.get("risk_level", "unknown")
        ),
    )

    col4.metric(
        "Workflow Status",
        format_name(
            state.get("workflow_status", "unknown")
        ),
    )

    # --------------------------------------------------------
    # Classification details
    # --------------------------------------------------------

    st.subheader("AI Document Classification")

    st.write(
        "**Detected Type:**",
        format_name(
            state.get("document_type", "unknown")
        ),
    )

    st.write(
        "**Model-Reported Confidence:**",
        f"{state.get('classification_confidence', 0) * 100:.2f}%",
    )

    evidence = state.get(
        "classification_evidence", []
    )

    if evidence:
        with st.expander("Classification Evidence"):
            for item in evidence:
                st.write(f"- {item}")

    # --------------------------------------------------------
    # AI extraction
    # --------------------------------------------------------

    st.subheader("AI-Extracted Information")

    st.caption(
        "Values extracted by the Groq-powered "
        "Information Extraction Agent."
    )

    fields = state.get("extracted_fields", {})

    if fields:

        left, right = st.columns(2)

        for index, (field, value) in enumerate(
            fields.items()
        ):

            column = left if index % 2 == 0 else right

            with column:
                st.text_input(
                    format_name(field),
                    value=(
                        str(value)
                        if value is not None
                        else ""
                    ),
                    disabled=True,
                    key=(
                        f"extracted_"
                        f"{result['document_id']}_"
                        f"{result['run_id']}_{field}"
                    ),
                )

    else:
        st.info(
            "No structured fields were extracted."
        )

    with st.expander("Field Evidence"):
        st.json(
            state.get("field_evidence", {})
        )

    optional_missing = state.get("missing_optional_fields", [])
    if optional_missing:
        st.caption("Optional fields not extracted: " + ", ".join(format_name(field) for field in optional_missing))

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    st.divider()
    st.subheader("Validation Agent")

    if state.get("validation_passed"):

        st.success(
            "Preliminary field validation passed."
        )

    else:

        st.warning(
            "Validation failed or manual verification "
            "is required."
        )

    errors = state.get(
        "validation_errors", []
    )

    warnings = state.get(
        "validation_warnings", []
    )

    if errors:
        st.write("**Validation Errors**")

        for error in errors:
            st.error(error)

    if warnings:
        st.write("**Validation Warnings**")

        for warning in warnings:
            st.warning(warning)

    if not errors and not warnings:
        st.write(
            "No validation problems reported."
        )

    # --------------------------------------------------------
    # Anomaly detection
    # --------------------------------------------------------

    st.divider()
    st.subheader("Anomaly Detection Agent")

    anomalies = state.get(
        "anomalies", []
    )

    if anomalies:
        display_issues(anomalies)
    else:
        st.success(
            "No anomalies detected by the current rules."
        )

    # --------------------------------------------------------
    # Cross-document verification
    # --------------------------------------------------------

    st.divider()
    st.subheader("Cross-Document Verification")

    cross_status = state.get(
        "cross_document_status",
        "not_checked",
    )

    st.write(
        "**Verification Status:**",
        format_name(cross_status),
    )

    matched_id = state.get(
        "matched_document_id"
    )

    if matched_id is not None:
        st.write(
            "**Matched Purchase Order ID:**",
            matched_id,
        )

    cross_issues = state.get(
        "cross_document_issues",
        [],
    )

    if cross_issues:

        display_issues(cross_issues)

    elif cross_status == "matched":

        st.success(
            "Matching Purchase Order found. "
            "Implemented comparisons passed."
        )

    elif cross_status == "not_checked":

        st.info(
            "Cross-document verification was not "
            "performed because no PO reference was found."
        )

    elif cross_status == "not_applicable":

        st.info(
            "Cross-document verification does not "
            "apply to this document type."
        )

    # --------------------------------------------------------
    # Workflow routing
    # --------------------------------------------------------

    st.divider()
    st.subheader("Workflow Routing Agent")

    st.write(
        "**Workflow Status:**",
        format_name(
            state.get("workflow_status", "unknown")
        ),
    )

    st.write(
        "**Assigned Department:**",
        state.get(
            "assigned_department",
            "Unknown"
        ),
    )

    st.write(
        "**Routing Reason:**",
        state.get(
            "routing_reason",
            "No reason available."
        ),
    )

    # --------------------------------------------------------
    # Agent execution history
    # --------------------------------------------------------

    with st.expander("Agent Execution History"):

        history = state.get(
            "agent_history", []
        )

        if history:
            for index, agent in enumerate(
                history,
                start=1,
            ):
                st.write(
                    f"{index}. {format_name(agent)}"
                )
        else:
            st.info(
                "No agent execution history available."
            )

    # --------------------------------------------------------
    # OCR text
    # --------------------------------------------------------

    with st.expander("View Full OCR Text"):

        st.text_area(
            "Recognized Document Text",
            value=state.get(
                "ocr_text",
                "",
            ),
            height=350,
            disabled=True,
            key=(
                f"ocr_{result['document_id']}_"
                f"{result['run_id']}"
            ),
        )

    # --------------------------------------------------------
    # JSON export
    # --------------------------------------------------------

    st.download_button(
        "Download Processing Result (JSON)",
        data=json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        ),
        file_name=(
            f"document_{result['document_id']}_"
            f"run_{result['run_id']}.json"
        ),
        mime="application/json",
        width="stretch",
    )


# ============================================================
# APPLICATION HEADER
# ============================================================

st.title(
    "Enterprise Intelligent Document Processing"
)

st.caption(
    "RapidOCR • Groq AI • LangGraph Multi-Agent System • "
    "Cross-Document Verification • SQLite"
)

st.divider()


# ============================================================
# APPLICATION TABS
# ============================================================

(
    tab_process,
    tab_history,
    tab_review,
    tab_analytics,
) = st.tabs(
    [
        "Document Processing",
        "Document History",
        "Manual Review",
        "Analytics Dashboard",
    ]
)


# ============================================================
# TAB 1 — DOCUMENT PROCESSING
# ============================================================

with tab_process:

    st.header("Upload and Process Document")

    uploaded_file = st.file_uploader(
        "Choose a document",
        type=[
            "pdf",
            "jpg",
            "jpeg",
            "png",
        ],
        key="document_uploader",
        on_change=clear_processing_result,
    )

    if uploaded_file is None:

        st.info(
            "Upload an invoice, purchase order, "
            "receipt, or contract to begin."
        )

    else:

        st.success(
            f"Selected document: {uploaded_file.name}"
        )

        # Show a preview for image files.

        if uploaded_file.type.startswith("image/"):

            st.subheader("Document Preview")

            st.image(
                uploaded_file,
                width=500,
            )

        # ----------------------------------------------------
        # Reprocessing option
        # ----------------------------------------------------

        force_reprocess = st.checkbox(
            "Reprocess even if document already exists",
            value=False,
            help=(
                "When enabled, the document is processed "
                "again using OCR and the agent workflow. "
                "The latest result replaces the previously "
                "stored result and consumes Groq API usage."
            ),
        )

        if force_reprocess:

            st.info(
                "Forced reprocessing is enabled. "
                "The existing document's latest stored "
                "result will be updated."
            )

        # ----------------------------------------------------
        # Process button
        # ----------------------------------------------------

        if st.button(
            "Process with AI Agents",
            type="primary",
            width="stretch",
        ):

            temporary_path = None

            # Clear previous output before new processing.

            st.session_state.pop(
                "last_result",
                None,
            )

            try:

                with st.spinner(
                    "Processing document with AI agents..."
                ):

                    file_suffix = Path(
                        uploaded_file.name
                    ).suffix

                    with tempfile.NamedTemporaryFile(
                        delete=False,
                        suffix=file_suffix,
                    ) as temporary_file:

                        file_bytes = uploaded_file.getvalue()

                        temporary_file.write(
                            file_bytes
                        )

                        temporary_path = Path(
                            temporary_file.name
                        )

                    result = pipeline.process(
                        file_path=temporary_path,
                        original_filename=uploaded_file.name,
                        force_reprocess=force_reprocess,
                    )

                    st.session_state[
                        "last_result"
                    ] = result

                    st.session_state[
                        "last_upload_hash"
                    ] = hashlib.sha256(
                        file_bytes
                    ).hexdigest()

                st.success(
                    result["message"]
                )

            except Exception as error:

                st.error(
                    "Document processing failed."
                )

                status = getattr(error, "status_code", None)
                if status == 429:
                    st.warning("Groq usage limit reached. Wait before retrying processing.")
                elif status in {401, 403}:
                    st.warning("Groq authentication failed. Check the configured credentials.")
                else:
                    st.caption("Check the document and service availability before retrying.")

            finally:

                if (
                    temporary_path is not None
                    and temporary_path.exists()
                ):

                    temporary_path.unlink()

        # ----------------------------------------------------
        # Display most recent result
        # ----------------------------------------------------

        last_result = st.session_state.get(
            "last_result"
        )

        if last_result is not None:

            current_hash = hashlib.sha256(
                uploaded_file.getvalue()
            ).hexdigest()

            stored_hash = st.session_state.get(
                "last_upload_hash"
            )

            if current_hash == stored_hash:
                show_processing_result(
                    last_result
                )


# ============================================================
# TAB 2 — DOCUMENT HISTORY
# ============================================================

with tab_history:

    st.header(
        "Processed Document History"
    )

    documents = repository.list_documents(
        limit=500
    )

    runs = repository.list_processing_runs(
        limit=500
    )

    if documents:

        st.dataframe(
            documents,
            width="stretch",
            hide_index=True,
        )

        st.subheader(
            "Inspect Stored Document"
        )

        document_ids = [
            document["id"]
            for document in documents
        ]

        selected_id = st.selectbox(
            "Select Document ID",
            options=document_ids,
            key="history_document_id",
        )

        stored_document = repository.get_document(
            selected_id
        )

        if stored_document:

            st.write(
                "**Filename:**",
                stored_document["filename"],
            )

            st.write(
                "**Document Type:**",
                format_name(
                    stored_document["document_type"]
                ),
            )

            st.write(
                "**Workflow Status:**",
                format_name(
                    stored_document["workflow_status"]
                ),
            )

            st.write(
                "**Review Decision:**",
                format_name(
                    stored_document["review_decision"]
                ),
            )

            with st.expander(
                "Stored AI-Extracted Information"
            ):

                st.json(
                    stored_document["extracted_data"]
                )

            with st.expander(
                "Complete Stored Agent State"
            ):

                st.json(
                    stored_document["full_result"]
                )

    else:

        st.info(
            "No documents have been processed yet."
        )

    st.divider()

    with st.expander(
        "View Processing Run History"
    ):

        if runs:

            st.dataframe(
                runs,
                width="stretch",
                hide_index=True,
            )

        else:

            st.info(
                "No processing runs recorded."
            )


# ============================================================
# TAB 3 — MANUAL REVIEW
# ============================================================

with tab_review:

    st.header(
        "Human Review Queue"
    )

    st.caption(
        "Demo workflow for reviewing extracted "
        "information and routing decisions."
    )

    documents = repository.list_documents(
        limit=500
    )

    review_queue = [
        document
        for document in documents
        if (
            document["review_decision"]
            == "pending"
        )
    ]

    if not review_queue:

        st.success(
            "No documents are awaiting a recorded "
            "review decision."
        )

    else:

        st.dataframe(
            review_queue,
            width="stretch",
            hide_index=True,
        )

        selected_id = st.selectbox(
            "Select Document for Review",
            options=[
                document["id"]
                for document in review_queue
            ],
            key="review_document_id",
        )

        selected_document = repository.get_document(
            selected_id
        )

        if selected_document:

            st.subheader(
                "Document Information"
            )

            st.write(
                "**Filename:**",
                selected_document["filename"],
            )

            st.write(
                "**Document Type:**",
                format_name(
                    selected_document["document_type"]
                ),
            )

            st.write(
                "**Workflow Status:**",
                format_name(
                    selected_document["workflow_status"]
                ),
            )

            stored_state = selected_document[
                "full_result"
            ]

            st.write(
                "**Assigned Department:**",
                stored_state.get(
                    "assigned_department",
                    "Unknown"
                ),
            )

            with st.expander(
                "Review Extracted Fields"
            ):

                st.json(
                    stored_state.get(
                        "extracted_fields",
                        {},
                    )
                )

            with st.expander(
                "Review Validation and Anomalies"
            ):

                st.write(
                    "**Validation Errors:**"
                )

                st.json(
                    stored_state.get(
                        "validation_errors",
                        [],
                    )
                )

                st.write(
                    "**Anomalies:**"
                )

                st.json(
                    stored_state.get(
                        "anomalies",
                        [],
                    )
                )

                st.write(
                    "**Cross-Document Issues:**"
                )

                st.json(
                    stored_state.get(
                        "cross_document_issues",
                        [],
                    )
                )

            # ------------------------------------------------
            # Human review decision
            # ------------------------------------------------

            decision = st.selectbox(
                "Review Decision",
                options=[
                    "approved",
                    "rejected",
                    "needs_correction",
                ],
                key=f"review_decision_select_{selected_id}",
            )

            notes = st.text_area(
                "Review Notes",
                placeholder=(
                    "Explain why this document "
                    "is being approved, rejected, "
                    "or returned for correction."
                ),
                key=f"review_notes_{selected_id}",
            )

            if st.button(
                "Save Review Decision",
                type="primary",
                width="stretch",
            ):

                if not notes.strip():

                    st.warning(
                        "Please provide review notes."
                    )

                else:

                    updated = repository.update_review(
                        document_id=selected_id,
                        decision=decision,
                        notes=notes.strip(),
                    )

                    if updated:

                        st.success(
                            "Review decision saved."
                        )

                        st.rerun()

                    else:

                        st.error(
                            "Document could not be updated."
                        )


# ============================================================
# TAB 4 — ANALYTICS DASHBOARD
# ============================================================

with tab_analytics:

    st.header(
        "Document Analytics Dashboard"
    )

    documents = repository.list_documents(
        limit=1000
    )

    runs = repository.list_processing_runs(
        limit=1000
    )

    unique_documents = len(
        documents
    )

    processing_runs = len(
        runs
    )

    duplicate_uploads = sum(
        1
        for run in runs
        if run["is_duplicate"]
    )

    pending_reviews = sum(
        1
        for document in documents
        if document["review_decision"] == "pending"
    )

    # --------------------------------------------------------
    # Dashboard metrics
    # --------------------------------------------------------

    metric1, metric2, metric3, metric4 = st.columns(4)

    metric1.metric(
        "Unique Documents",
        unique_documents,
    )

    metric2.metric(
        "Processing Runs",
        processing_runs,
    )

    metric3.metric(
        "Exact Duplicate Uploads",
        duplicate_uploads,
    )

    metric4.metric(
        "Pending Review Decisions",
        pending_reviews,
    )

    # --------------------------------------------------------
    # Document type analytics
    # --------------------------------------------------------

    if documents:

        st.divider()

        st.subheader(
            "Document Type Distribution"
        )

        type_counts = {}

        for document in documents:

            document_type = document[
                "document_type"
            ]

            type_counts[document_type] = (
                type_counts.get(
                    document_type,
                    0,
                ) + 1
            )

        st.bar_chart(
            type_counts
        )

        # ----------------------------------------------------
        # Workflow analytics
        # ----------------------------------------------------

        st.subheader(
            "Workflow Status Distribution"
        )

        status_counts = {}

        for document in documents:

            status = document[
                "workflow_status"
            ]

            status_counts[status] = (
                status_counts.get(
                    status,
                    0,
                ) + 1
            )

        st.bar_chart(
            status_counts
        )

        # ----------------------------------------------------
        # Review analytics
        # ----------------------------------------------------

        st.subheader(
            "Review Decision Distribution"
        )

        review_counts = {}

        for document in documents:

            review = document[
                "review_decision"
            ]

            review_counts[review] = (
                review_counts.get(
                    review,
                    0,
                ) + 1
            )

        st.bar_chart(
            review_counts
        )

    else:

        st.info(
            "Analytics will appear after documents "
            "have been processed."
        )

    st.caption(
        "These charts summarize the latest records "
        "retrieved from SQLite, with a maximum of "
        "1,000 records per query."
    )

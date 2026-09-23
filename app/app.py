from pathlib import Path
import tempfile

import streamlit as st

from idp.ocr.rapidocr_engine import RapidOCREngine
from idp.pipeline.document_pipeline import DocumentPipeline


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Intelligent Document Processing",
    page_icon="📄",
    layout="wide",
)


# ============================================================
# PIPELINE INITIALIZATION
# ============================================================

@st.cache_resource
def create_pipeline():

    ocr_engine = RapidOCREngine()

    return DocumentPipeline(
        ocr_engine=ocr_engine
    )


pipeline = create_pipeline()


# ============================================================
# HEADER
# ============================================================

st.title(
    "AI-Based Intelligent Document Processing System"
)

st.caption(
    "OCR • Document Classification • "
    "Information Extraction • Validation"
)

st.divider()


# ============================================================
# DOCUMENT UPLOAD
# ============================================================

uploaded_file = st.file_uploader(
    "Upload a document",
    type=[
        "jpg",
        "jpeg",
        "png",
        "pdf",
    ],
)


if uploaded_file is None:

    st.info(
        "Upload an invoice to begin document processing."
    )

else:

    st.success(
        f"Selected document: {uploaded_file.name}"
    )

    file_suffix = Path(
        uploaded_file.name
    ).suffix


    # ========================================================
    # DOCUMENT PREVIEW
    # ========================================================

    if uploaded_file.type.startswith("image"):

        st.subheader("Document Preview")

        st.image(
            uploaded_file,
            width=500,
        )


    # ========================================================
    # PROCESS BUTTON
    # ========================================================

    process_button = st.button(
        "Process Document",
        type="primary",
        use_container_width=True,
    )


    if process_button:

        temporary_path = None

        try:

            # =================================================
            # DOCUMENT PROCESSING
            # =================================================

            with st.spinner(
                "Processing document..."
            ):

                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=file_suffix,
                ) as temporary_file:

                    temporary_file.write(
                        uploaded_file.getvalue()
                    )

                    temporary_path = Path(
                        temporary_file.name
                    )

                result = pipeline.process(
                    temporary_path
                )


            st.success(
                "Document processed successfully."
            )

            st.divider()


            # =================================================
            # DOCUMENT ANALYSIS
            # =================================================

            st.header(
                "Document Analysis"
            )

            (
                column1,
                column2,
                column3,
                column4,
            ) = st.columns(4)


            # Document Type
            column1.metric(
                "Document Type",
                result.classification
                .document_class
                .value
                .replace("_", " ")
                .title(),
            )


            # OCR Confidence
            column2.metric(
                "OCR Confidence",
                (
                    f"{result.ocr.average_confidence * 100:.2f}%"
                ),
            )


            # Number of Pages
            column3.metric(
                "Pages",
                result.ocr.total_pages,
            )


            # Validation Status
            if result.validation:

                validation_status = (
                    "Auto Accepted"
                    if not result.validation.requires_review
                    else "Review Required"
                )

                column4.metric(
                    "Validation",
                    validation_status,
                )

            else:

                column4.metric(
                    "Validation",
                    "N/A",
                )


            st.divider()


            # =================================================
            # EXTRACTED INFORMATION
            # =================================================

            if result.extracted_data:

                st.header(
                    "Extracted Information"
                )

                invoice = result.extracted_data

                (
                    left_column,
                    right_column,
                ) = st.columns(2)


                # ---------------------------------------------
                # LEFT COLUMN
                # ---------------------------------------------

                with left_column:

                    st.text_input(
                        "Invoice Number",
                        value=(
                            invoice.invoice_number
                            or ""
                        ),
                        disabled=True,
                    )

                    st.text_input(
                        "Issue Date",
                        value=(
                            invoice.issue_date
                            or ""
                        ),
                        disabled=True,
                    )

                    st.text_input(
                        "Seller",
                        value=(
                            invoice.seller
                            or ""
                        ),
                        disabled=True,
                    )

                    st.text_input(
                        "Client",
                        value=(
                            invoice.client
                            or ""
                        ),
                        disabled=True,
                    )


                # ---------------------------------------------
                # RIGHT COLUMN
                # ---------------------------------------------

                with right_column:

                    st.text_input(
                        "Tax ID",
                        value=(
                            invoice.tax_id
                            or ""
                        ),
                        disabled=True,
                    )

                    st.text_input(
                        "IBAN",
                        value=(
                            invoice.iban
                            or ""
                        ),
                        disabled=True,
                    )

                    st.text_input(
                        "Total",
                        value=(
                            invoice.total
                            or ""
                        ),
                        disabled=True,
                    )


                    if result.validation:

                        st.text_input(
                            "Validation Score",
                            value=(
                                f"{result.validation.validation_score * 100:.2f}%"
                            ),
                            disabled=True,
                        )


            # =================================================
            # VALIDATION DETAILS
            # =================================================

            if result.validation:

                st.divider()

                st.header(
                    "Validation Details"
                )


                # ---------------------------------------------
                # AUTOMATIC DECISION
                # ---------------------------------------------

                if not result.validation.requires_review:

                    st.success(
                        "Document passed automatic validation "
                        "and can be accepted."
                    )

                else:

                    st.warning(
                        "Document requires manual review because "
                        "one or more fields are missing or invalid."
                    )


                # ---------------------------------------------
                # MISSING FIELDS
                # ---------------------------------------------

                if result.validation.missing_fields:

                    st.write(
                        "**Missing fields:**"
                    )

                    for field in (
                        result.validation.missing_fields
                    ):

                        st.write(
                            f"- {field}"
                        )


                # ---------------------------------------------
                # INVALID FIELDS
                # ---------------------------------------------

                if result.validation.invalid_fields:

                    st.write(
                        "**Invalid fields:**"
                    )

                    for field in (
                        result.validation.invalid_fields
                    ):

                        st.write(
                            f"- {field}"
                        )


                # ---------------------------------------------
                # WARNINGS
                # ---------------------------------------------

                if result.validation.warnings:

                    st.write(
                        "**Warnings:**"
                    )

                    for warning in (
                        result.validation.warnings
                    ):

                        st.write(
                            f"- {warning}"
                        )


                # ---------------------------------------------
                # VALIDATION SCORE
                # ---------------------------------------------

                st.write(
                    "**Required-field validation score:** "
                    f"{result.validation.validation_score * 100:.2f}%"
                )


            # =================================================
            # OCR DETAILS
            # =================================================

            st.divider()

            with st.expander(
                "View Full OCR Text"
            ):

                st.text_area(
                    "Extracted Text",
                    value=result.ocr.full_text,
                    height=400,
                    disabled=True,
                )


            # =================================================
            # CLASSIFICATION DETAILS
            # =================================================

            with st.expander(
                "Classification Details"
            ):

                st.write(
                    "**Classification confidence:** "
                    f"{result.classification.confidence * 100:.2f}%"
                )

                st.write(
                    "**Matched keywords:**"
                )

                if result.classification.matched_keywords:

                    st.write(
                        ", ".join(
                            result.classification.matched_keywords
                        )
                    )

                else:

                    st.write(
                        "No classification keywords matched."
                    )


        # =====================================================
        # ERROR HANDLING
        # =====================================================

        except Exception as error:

            st.error(
                "Document processing failed."
            )

            st.exception(
                error
            )


        # =====================================================
        # TEMPORARY FILE CLEANUP
        # =====================================================

        finally:

            if (
                temporary_path is not None
                and temporary_path.exists()
            ):

                temporary_path.unlink()
from pathlib import Path
import tempfile

import streamlit as st

from idp.models.classification import DocumentClass
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
        "Upload a document to begin processing."
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

        st.subheader(
            "Document Preview"
        )

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


            column1.metric(
                "Document Type",
                result.classification
                .document_class
                .value
                .replace("_", " ")
                .title(),
            )


            column2.metric(
                "OCR Confidence",
                (
                    f"{result.ocr.average_confidence * 100:.2f}%"
                ),
            )


            column3.metric(
                "Pages",
                result.ocr.total_pages,
            )


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

                extracted = (
                    result.extracted_data
                )

                document_class = (
                    result.classification.document_class
                )

                (
                    left_column,
                    right_column,
                ) = st.columns(2)


                # =============================================
                # INVOICE INFORMATION
                # =============================================

                if (
                    document_class
                    == DocumentClass.INVOICE
                ):

                    with left_column:

                        st.text_input(
                            "Invoice Number",
                            value=(
                                extracted.invoice_number
                                or ""
                            ),
                            disabled=True,
                        )

                        st.text_input(
                            "Issue Date",
                            value=(
                                extracted.issue_date
                                or ""
                            ),
                            disabled=True,
                        )

                        st.text_input(
                            "Seller",
                            value=(
                                extracted.seller
                                or ""
                            ),
                            disabled=True,
                        )

                        st.text_input(
                            "Client",
                            value=(
                                extracted.client
                                or ""
                            ),
                            disabled=True,
                        )


                    with right_column:

                        st.text_input(
                            "Tax ID",
                            value=(
                                extracted.tax_id
                                or ""
                            ),
                            disabled=True,
                        )

                        st.text_input(
                            "IBAN",
                            value=(
                                extracted.iban
                                or ""
                            ),
                            disabled=True,
                        )

                        st.text_input(
                            "Total",
                            value=(
                                extracted.total
                                or ""
                            ),
                            disabled=True,
                        )


                # =============================================
                # PURCHASE ORDER INFORMATION
                # =============================================

                elif (
                    document_class
                    == DocumentClass.PURCHASE_ORDER
                ):

                    with left_column:

                        st.text_input(
                            "PO Number",
                            value=(
                                extracted.po_number
                                or ""
                            ),
                            disabled=True,
                        )

                        st.text_input(
                            "Order Date",
                            value=(
                                extracted.order_date
                                or ""
                            ),
                            disabled=True,
                        )

                        st.text_input(
                            "Vendor",
                            value=(
                                extracted.vendor
                                or ""
                            ),
                            disabled=True,
                        )


                    with right_column:

                        st.text_input(
                            "Bill To",
                            value=(
                                extracted.bill_to
                                or ""
                            ),
                            disabled=True,
                        )

                        st.text_input(
                            "Ship To",
                            value=(
                                extracted.ship_to
                                or ""
                            ),
                            disabled=True,
                        )

                        st.text_input(
                            "Total",
                            value=(
                                extracted.total
                                or ""
                            ),
                            disabled=True,
                        )


                # =============================================
                # VALIDATION SCORE
                # =============================================

                if result.validation:

                    st.write(
                        "**Validation Score:** "
                        f"{result.validation.validation_score * 100:.2f}%"
                    )


            # =================================================
            # NO EXTRACTOR AVAILABLE
            # =================================================

            else:

                document_class = (
                    result.classification
                    .document_class
                )

                if (
                    document_class
                    not in {
                        DocumentClass.UNKNOWN,
                    }
                ):

                    st.info(
                        "The document was classified successfully, "
                        "but structured extraction for this document "
                        "type has not been implemented yet."
                    )


            # =================================================
            # VALIDATION DETAILS
            # =================================================

            if result.validation:

                st.divider()

                st.header(
                    "Validation Details"
                )


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
                # Missing fields
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
                # Invalid fields
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
                # Warnings
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

                if (
                    result.classification
                    .matched_keywords
                ):

                    st.write(
                        ", ".join(
                            result.classification
                            .matched_keywords
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
from pathlib import Path

from idp.classification.keyword_classifier import KeywordDocumentClassifier

from idp.extraction.invoice_extractor import InvoiceExtractor
from idp.extraction.purchase_order_extractor import PurchaseOrderExtractor

from idp.ingestion.document_loader import DocumentLoader
from idp.ingestion.page_processor import PageProcessor

from idp.models.classification import DocumentClass
from idp.models.processing import ProcessingResult

from idp.ocr.base import BaseOCREngine
from idp.ocr.processor import OCRProcessor

from idp.validation.invoice_validator import InvoiceValidator
from idp.validation.purchase_order_validator import PurchaseOrderValidator


class DocumentPipeline:

    def __init__(
        self,
        ocr_engine: BaseOCREngine
    ):

        # ---------------------------------------------
        # Document ingestion
        # ---------------------------------------------

        self.document_loader = DocumentLoader()

        self.page_processor = PageProcessor()


        # ---------------------------------------------
        # OCR
        # ---------------------------------------------

        self.ocr_processor = OCRProcessor(
            engine=ocr_engine
        )


        # ---------------------------------------------
        # Classification
        # ---------------------------------------------

        self.classifier = (
            KeywordDocumentClassifier()
        )


        # ---------------------------------------------
        # Invoice processing
        # ---------------------------------------------

        self.invoice_extractor = (
            InvoiceExtractor()
        )

        self.invoice_validator = (
            InvoiceValidator()
        )


        # ---------------------------------------------
        # Purchase Order processing
        # ---------------------------------------------

        self.purchase_order_extractor = (
            PurchaseOrderExtractor()
        )

        self.purchase_order_validator = (
            PurchaseOrderValidator()
        )


    def process(
        self,
        file_path: str | Path
    ) -> ProcessingResult:

        # =============================================
        # STEP 1: LOAD DOCUMENT
        # =============================================

        document = self.document_loader.load(
            file_path
        )


        # =============================================
        # STEP 2: CONVERT DOCUMENT INTO PAGES
        # =============================================

        pages = self.page_processor.process(
            document
        )


        # =============================================
        # STEP 3: OCR
        # =============================================

        ocr_result = self.ocr_processor.process(
            document=document,
            pages=pages,
        )


        # =============================================
        # STEP 4: CLASSIFICATION
        # =============================================

        classification = (
            self.classifier.classify(
                ocr_result.full_text
            )
        )


        # =============================================
        # PREPARE OCR REGIONS
        # =============================================

        all_regions = [
            region
            for page in ocr_result.pages
            for region in page.regions
        ]


        # =============================================
        # DEFAULT RESULTS
        # =============================================

        extracted_data = None
        validation = None


        # =============================================
        # STEP 5A: INVOICE PIPELINE
        # =============================================

        if (
            classification.document_class
            == DocumentClass.INVOICE
        ):

            extracted_data = (
                self.invoice_extractor.extract(
                    text=ocr_result.full_text,
                    regions=all_regions,
                )
            )

            validation = (
                self.invoice_validator.validate(
                    extracted_data
                )
            )


        # =============================================
        # STEP 5B: PURCHASE ORDER PIPELINE
        # =============================================

        elif (
            classification.document_class
            == DocumentClass.PURCHASE_ORDER
        ):

            extracted_data = (
                self.purchase_order_extractor.extract(
                    text=ocr_result.full_text
                )
            )

            validation = (
                self.purchase_order_validator.validate(
                    extracted_data
                )
            )


        # =============================================
        # STEP 6: RETURN COMPLETE RESULT
        # =============================================

        return ProcessingResult(
            filename=document.filename,
            ocr=ocr_result,
            classification=classification,
            extracted_data=extracted_data,
            validation=validation,
        )
from pathlib import Path

from idp.classification.keyword_classifier import (KeywordDocumentClassifier)
from idp.extraction.invoice_extractor import (InvoiceExtractor)
from idp.ingestion.document_loader import (DocumentLoader)
from idp.ingestion.page_processor import (PageProcessor)
from idp.models.classification import (DocumentClass)
from idp.models.processing import (ProcessingResult)
from idp.ocr.base import BaseOCREngine
from idp.ocr.processor import OCRProcessor
from idp.validation.invoice_validator import (InvoiceValidator)


class DocumentPipeline:
    def __init__(self, ocr_engine: BaseOCREngine):

        self.document_loader = DocumentLoader()
        self.page_processor = PageProcessor()

        self.ocr_processor = OCRProcessor(engine=ocr_engine)

        self.classifier = (KeywordDocumentClassifier())

        self.invoice_extractor = (InvoiceExtractor())

        self.invoice_validator = (InvoiceValidator())

    def process(self, file_path: str | Path) -> ProcessingResult:

        document = self.document_loader.load( file_path)

        pages = self.page_processor.process(document)

        ocr_result = self.ocr_processor.process(document=document, pages=pages)

        classification = self.classifier.classify(ocr_result.full_text)

        extracted_data = None
        validation = None

        if (classification.document_class == DocumentClass.INVOICE):

            all_regions = [
                region
                for page in ocr_result.pages
                for region in page.regions
            ]

            extracted_data = (
                self.invoice_extractor.extract(text=ocr_result.full_text, regions=all_regions)
            )

            validation = (
                self.invoice_validator.validate(extracted_data)
            )

        return ProcessingResult(filename=document.filename, ocr=ocr_result, classification=classification, extracted_data=extracted_data, validation=validation)
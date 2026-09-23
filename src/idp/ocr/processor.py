from idp.models.document import Document
from idp.models.page import DocumentPage
from idp.models.ocr import DocumentOCRResult
from idp.ocr.base import BaseOCREngine


class OCRProcessor:
    def __init__(self, engine: BaseOCREngine):
        self.engine = engine

    def process(self, document: Document, pages: list[DocumentPage]) -> DocumentOCRResult:

        page_results = []

        for page in pages:

            result = self.engine.process(image=page.image, page_number=page.page_number)

            page_results.append(result)

        full_text = "\n\n".join(result.full_text for result in page_results)

        all_confidences = [
            region.confidence
            for result in page_results
            for region in result.regions
        ]

        average_confidence = (
            sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
        )

        return DocumentOCRResult(filename=document.filename, total_pages=len(page_results), full_text=full_text, average_confidence=average_confidence, pages=page_results)
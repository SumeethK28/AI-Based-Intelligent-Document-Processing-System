from dataclasses import dataclass

from idp.models.classification import ClassificationResult
from idp.models.invoice import InvoiceData
from idp.models.ocr import DocumentOCRResult
from idp.models.validation import ValidationResult


@dataclass
class ProcessingResult:
    filename: str
    ocr: DocumentOCRResult
    classification: ClassificationResult
    extracted_data: InvoiceData | None
    validation: ValidationResult | None
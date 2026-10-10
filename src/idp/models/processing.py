from dataclasses import dataclass

from idp.models.classification import ClassificationResult
from idp.models.invoice import InvoiceData
from idp.models.ocr import DocumentOCRResult
from idp.models.validation import ValidationResult

from idp.models.invoice import InvoiceData
from idp.models.purchase_order import PurchaseOrderData
from idp.models.receipt import ReceiptData

@dataclass
class ProcessingResult:
    filename: str
    ocr: DocumentOCRResult
    classification: ClassificationResult
    extracted_data: InvoiceData | PurchaseOrderData | ReceiptData | None
    validation: ValidationResult | None
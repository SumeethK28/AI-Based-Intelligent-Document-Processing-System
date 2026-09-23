from dataclasses import dataclass
from enum import Enum


class DocumentClass(Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    PURCHASE_ORDER = "purchase_order"
    CONTRACT = "contract"
    UNKNOWN = "unknown"


@dataclass
class ClassificationResult:
    document_class: DocumentClass
    confidence: float
    matched_keywords: list[str]
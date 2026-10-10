
from typing import Literal

from pydantic import BaseModel, Field


DocumentType = Literal[
    "invoice",
    "purchase_order",
    "receipt",
    "contract",
    "unknown",
]


class AIClassificationResult(BaseModel):
    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class AIExtractionResult(BaseModel):
    # General document fields. Only the applicable
    # fields should be populated.

    invoice_number: str | None = None
    po_number: str | None = None
    receipt_number: str | None = None

    issue_date: str | None = None
    order_date: str | None = None

    seller: str | None = None
    client: str | None = None
    vendor: str | None = None
    buyer: str | None = None

    bill_to: str | None = None
    ship_to: str | None = None

    tax_id: str | None = None
    iban: str | None = None

    subtotal: str | None = None
    tax: str | None = None
    total: str | None = None

    po_reference: str | None = None

    # Evidence helps us check hallucinations later.
    field_evidence: dict[str, str] = Field(
        default_factory=dict
    )

    # This is a self-reported model estimate,
    # not calibrated extraction accuracy.
    confidence: float = Field(ge=0.0, le=1.0)

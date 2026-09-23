from dataclasses import dataclass


@dataclass
class ReceiptData:
    merchant: str | None = None
    receipt_number: str | None = None
    date: str | None = None
    subtotal: str | None = None
    tax: str | None = None
    total: str | None = None
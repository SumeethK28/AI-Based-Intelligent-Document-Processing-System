from dataclasses import dataclass


@dataclass
class InvoiceData:
    invoice_number: str | None = None
    issue_date: str | None = None
    seller: str | None = None
    client: str | None = None
    tax_id: str | None = None
    iban: str | None = None
    total: str | None = None
    seller_tax_id_evidence: str | None = None

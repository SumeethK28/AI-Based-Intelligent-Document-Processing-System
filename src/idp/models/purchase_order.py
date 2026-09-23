from dataclasses import dataclass


@dataclass
class PurchaseOrderData:
    po_number: str | None = None
    order_date: str | None = None
    vendor: str | None = None
    bill_to: str | None = None
    ship_to: str | None = None
    total: str | None = None
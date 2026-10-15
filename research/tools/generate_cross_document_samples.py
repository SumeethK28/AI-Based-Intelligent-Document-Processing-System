
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


OUTPUT = Path("data/samples/cross_document")
OUTPUT.mkdir(parents=True, exist_ok=True)


def create_document(filename: str, title: str, lines: list[str]):
    path = OUTPUT / filename
    pdf = canvas.Canvas(str(path), pagesize=A4)

    width, height = A4

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(50, height - 60, title)

    pdf.setFont("Helvetica", 12)

    y = height - 110

    for line in lines:
        pdf.drawString(50, y, line)
        y -= 28

    pdf.save()
    print("Created:", path)


def main():
    create_document(
        "purchase_order_1023.pdf",
        "PURCHASE ORDER",
        [
            "PO Number: PO-1023",
            "Vendor: ABC Technologies",
            "Buyer: XYZ Company",
            "Order Date: 10/10/2026",
            "Currency: INR",
            "Total: INR 42000.00",
        ],
    )

    create_document(
        "invoice_matching.pdf",
        "INVOICE",
        [
            "Invoice Number: INV-501",
            "Purchase Order Reference: PO-1023",
            "Seller: ABC Technologies",
            "Client: XYZ Company",
            "Issue Date: 10/10/2026",
            "Currency: INR",
            "Total: INR 42000.00",
        ],
    )

    create_document(
        "invoice_mismatch.pdf",
        "INVOICE",
        [
            "Invoice Number: INV-502",
            "Purchase Order Reference: PO-1023",
            "Seller: ABC Technologies",
            "Client: XYZ Company",
            "Issue Date: 10/10/2026",
            "Currency: INR",
            "Total: INR 50000.00",
        ],
    )

    create_document(
        "invoice_unknown_po.pdf",
        "INVOICE",
        [
            "Invoice Number: INV-503",
            "Purchase Order Reference: PO-9999",
            "Seller: ABC Technologies",
            "Client: XYZ Company",
            "Issue Date: 10/10/2026",
            "Currency: INR",
            "Total: INR 42000.00",
        ],
    )


if __name__ == "__main__":
    main()

"""Conservative label-based receipt fallback; never infer unlabeled values."""
import re
from idp.models.receipt import ReceiptData


class ReceiptExtractor:
    def extract(self, text: str) -> ReceiptData:
        labels = {
            "merchant": r"(?:merchant|seller|store)",
            "receipt_number": r"receipt(?:\s+(?:number|no\.?|#))?",
            "date": r"(?:date|transaction date)",
            "subtotal": r"sub\s*total",
            "tax": r"(?:tax|vat|gst)",
            "total": r"(?:grand total|total|amount paid)",
        }
        values = {}
        for field, label in labels.items():
            match = re.search(r"^\s*" + label + r"\s*[:#]\s*(\S[^\n]*)$", text, re.I | re.M)
            if match:
                values[field] = match.group(1).strip()
        return ReceiptData(**values)

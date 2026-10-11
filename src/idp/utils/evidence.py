import re


def normalize_evidence(value: str) -> str:
    """Normalize escaped line separators without relaxing OCR presence checks."""
    return value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")


def normalize_ocr_text(value) -> str:
    text = " ".join(str(value).casefold().split())
    return re.sub(r"([$€£₹])\s+(?=-?\d)", r"\1", text)

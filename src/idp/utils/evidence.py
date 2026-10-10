def normalize_evidence(value: str) -> str:
    """Normalize escaped line separators without relaxing OCR presence checks."""
    return value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")

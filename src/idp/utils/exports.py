"""Keep formula-like document text inert in spreadsheet-compatible tables."""


def spreadsheet_safe(value):
    if isinstance(value, str) and (value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + value
    return value

from idp.models.invoice import InvoiceData
from idp.models.validation import ValidationResult


class InvoiceValidator:

    REQUIRED_FIELDS = [
        "invoice_number",
        "issue_date",
        "seller",
        "client",
        "total",
    ]

    def validate(self, invoice: InvoiceData) -> ValidationResult:

        missing_fields = []

        for field_name in self.REQUIRED_FIELDS:

            value = getattr(invoice, field_name)

            if value is None or not str(value).strip():
                missing_fields.append(field_name)

        total_fields = len(self.REQUIRED_FIELDS)

        valid_fields = (
            total_fields - len(missing_fields)
        )

        validation_score = (
            valid_fields / total_fields
        )

        warnings = []

        if missing_fields:
            warnings.append("Required invoice fields are missing.")

        is_valid = len(missing_fields) == 0

        return ValidationResult(is_valid=is_valid, validation_score=validation_score, missing_fields=missing_fields, warnings=warnings)
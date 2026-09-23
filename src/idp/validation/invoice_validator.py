import re
from datetime import datetime

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
        invalid_fields = []
        warnings = []

        # ---------------------------------
        # Required-field validation
        # ---------------------------------

        for field_name in self.REQUIRED_FIELDS:

            value = getattr(
                invoice,
                field_name
            )

            if value is None or not str(value).strip():
                missing_fields.append(field_name)

        # ---------------------------------
        # Invoice number validation
        # ---------------------------------

        if (
            invoice.invoice_number
            and not self._valid_invoice_number(
                invoice.invoice_number
            )
        ):
            invalid_fields.append(
                "invoice_number"
            )

        # ---------------------------------
        # Date validation
        # ---------------------------------

        if (
            invoice.issue_date
            and not self._valid_date(
                invoice.issue_date
            )
        ):
            invalid_fields.append(
                "issue_date"
            )

        # ---------------------------------
        # Seller / client validation
        # ---------------------------------

        if (
            invoice.seller
            and self._looks_like_label(
                invoice.seller
            )
        ):
            invalid_fields.append(
                "seller"
            )

        if (
            invoice.client
            and self._looks_like_label(
                invoice.client
            )
        ):
            invalid_fields.append(
                "client"
            )

        # ---------------------------------
        # IBAN validation
        # ---------------------------------

        if (
            invoice.iban
            and not self._valid_iban(
                invoice.iban
            )
        ):
            invalid_fields.append(
                "iban"
            )

        # ---------------------------------
        # Total validation
        # ---------------------------------

        if (
            invoice.total
            and not self._valid_total(
                invoice.total
            )
        ):
            invalid_fields.append(
                "total"
            )

        # ---------------------------------
        # Validation score
        # ---------------------------------

        checked_fields = len(
            self.REQUIRED_FIELDS
        )

        problem_fields = set(
            missing_fields + invalid_fields
        )

        valid_field_count = (
            checked_fields
            - len(
                problem_fields.intersection(
                    self.REQUIRED_FIELDS
                )
            )
        )

        validation_score = (
            valid_field_count
            / checked_fields
        )

        # ---------------------------------
        # Warnings
        # ---------------------------------

        if missing_fields:

            warnings.append(
                "Required invoice fields are missing."
            )

        if invalid_fields:

            warnings.append(
                "One or more extracted fields "
                "failed format validation."
            )

        is_valid = (
            not missing_fields
            and not invalid_fields
        )

        requires_review = not is_valid

        return ValidationResult(
            is_valid=is_valid,
            validation_score=validation_score,
            missing_fields=missing_fields,
            invalid_fields=invalid_fields,
            warnings=warnings,
            requires_review=requires_review,
        )

    def _valid_invoice_number(self, value: str) -> bool:

        return bool(
            re.fullmatch(
                r"[A-Za-z0-9\-]+",
                value.strip()
            )
        )

    def _valid_date(self, value: str) -> bool:

        formats = [
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
        ]

        for date_format in formats:

            try:

                datetime.strptime(
                    value,
                    date_format
                )

                return True

            except ValueError:
                continue

        return False

    def _looks_like_label(self, value: str) -> bool:

        labels = {
            "seller:",
            "client:",
            "invoice:",
            "total:",
            "date:",
            "items",
            "summary",
        }

        return (value.strip().lower() in labels)

    def _valid_iban(self, value: str) -> bool:

        normalized = re.sub(
            r"\s+",
            "",
            value.upper()
        )

        return bool(
            re.fullmatch(
                r"[A-Z]{2}[0-9]{2}[A-Z0-9]{10,30}",
                normalized
            )
        )

    def _valid_total(self, value: str) -> bool:
        cleaned = (
            value
            .replace("$", "")
            .replace("€", "")
            .replace("£", "")
            .replace(" ", "")
            .strip()
        )

        return bool(re.fullmatch(r"\d+(?:[.,]\d{2})?", cleaned))
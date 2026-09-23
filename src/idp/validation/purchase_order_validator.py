import re
from datetime import datetime

from idp.models.purchase_order import PurchaseOrderData
from idp.models.validation import ValidationResult


class PurchaseOrderValidator:

    REQUIRED_FIELDS = [
        "po_number",
        "order_date",
        "vendor",
        "total",
    ]

    def validate(
        self,
        purchase_order: PurchaseOrderData
    ) -> ValidationResult:

        missing_fields = []
        invalid_fields = []
        warnings = []

        for field_name in self.REQUIRED_FIELDS:

            value = getattr(
                purchase_order,
                field_name
            )

            if (
                value is None
                or not str(value).strip()
            ):
                missing_fields.append(
                    field_name
                )

        if (
            purchase_order.po_number
            and not self._valid_po_number(
                purchase_order.po_number
            )
        ):
            invalid_fields.append(
                "po_number"
            )

        if (
            purchase_order.order_date
            and not self._valid_date(
                purchase_order.order_date
            )
        ):
            invalid_fields.append(
                "order_date"
            )

        if (
            purchase_order.total
            and not self._valid_total(
                purchase_order.total
            )
        ):
            invalid_fields.append(
                "total"
            )

        problem_fields = set(
            missing_fields + invalid_fields
        )

        valid_count = (
            len(self.REQUIRED_FIELDS)
            - len(
                problem_fields.intersection(
                    self.REQUIRED_FIELDS
                )
            )
        )

        validation_score = (
            valid_count
            / len(self.REQUIRED_FIELDS)
        )

        if missing_fields:
            warnings.append(
                "Required purchase order fields "
                "are missing."
            )

        if invalid_fields:
            warnings.append(
                "One or more purchase order fields "
                "failed format validation."
            )

        is_valid = (
            not missing_fields
            and not invalid_fields
        )

        return ValidationResult(
            is_valid=is_valid,
            validation_score=validation_score,
            missing_fields=missing_fields,
            invalid_fields=invalid_fields,
            warnings=warnings,
            requires_review=not is_valid,
        )

    def _valid_po_number(
        self,
        value: str
    ) -> bool:

        return bool(
            re.fullmatch(
                r"[A-Za-z0-9\-_\/]+",
                value.strip()
            )
        )

    def _valid_date(
        self,
        value: str
    ) -> bool:

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

    def _valid_total(
        self,
        value: str
    ) -> bool:

        cleaned = (
            value
            .replace("$", "")
            .replace("€", "")
            .replace("£", "")
            .replace("₹", "")
            .replace(",", "")
            .replace(" ", "")
            .strip()
        )

        return bool(
            re.fullmatch(
                r"\d+(?:\.\d{1,2})?",
                cleaned
            )
        )
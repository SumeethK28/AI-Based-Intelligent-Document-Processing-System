
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from idp.agents.state import DocumentState


class ValidationAgent:

    REQUIRED_FIELDS = {
        "invoice": [
            "invoice_number",
            "issue_date",
            "seller",
            "client",
            "total",
        ],
        "purchase_order": [
            "po_number",
            "order_date",
            "vendor",
        ],
        "receipt": [
            "total",
        ],
        # Contracts have varying structures.
        # We don't impose a universal field schema yet.
        "contract": [],
    }

    DATE_FIELDS = {
        "issue_date",
        "order_date",
    }

    AMOUNT_FIELDS = {
        "subtotal",
        "tax",
        "total",
    }

    @staticmethod
    def normalize_text(value: Any) -> str:
        return " ".join(str(value).casefold().split())

    @staticmethod
    def parse_date(value: str) -> bool:
        formats = (
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%m-%d-%Y",
        )

        for fmt in formats:
            try:
                datetime.strptime(value.strip(), fmt)
                return True
            except ValueError:
                continue

        return False

    @staticmethod
    def parse_amount(value: str) -> Decimal | None:
        """
        Accept unambiguous common currency formatting.
        Reject ambiguous single-separator amounts instead
        of guessing decimal conventions.
        """
        raw = str(value).strip()

        cleaned = re.sub(
            r"[$€£₹,\s]",
            "",
            raw,
        )

        # A comma may be a thousands separator, but
        # '$ 819,06' uses a decimal comma. Handle that.
        compact = re.sub(r"[$€£₹\s]", "", raw)

        if re.fullmatch(r"-?\d+,\d{2}", compact):
            cleaned = compact.replace(",", ".")

        elif re.fullmatch(
            r"-?\d{1,3}(,\d{3})+(\.\d{1,2})?",
            compact,
        ):
            cleaned = compact.replace(",", "")

        elif re.fullmatch(r"-?\d+(\.\d{1,2})?", compact):
            cleaned = compact

        else:
            return None

        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None

    def run(self, state: DocumentState) -> dict[str, Any]:

        document_type = state.get(
            "document_type",
            "unknown",
        )

        fields = state.get(
            "extracted_fields",
            {},
        )

        evidence = state.get(
            "field_evidence",
            {},
        )

        ocr_text = state.get(
            "ocr_text",
            "",
        )

        normalized_ocr = self.normalize_text(ocr_text)

        errors: list[str] = []
        warnings: list[str] = []

        # =============================================
        # STEP 1: DOCUMENT TYPE
        # =============================================

        if document_type not in self.REQUIRED_FIELDS:
            errors.append(
                f"Unsupported or unknown document type: "
                f"{document_type}"
            )

        # =============================================
        # STEP 2: REQUIRED FIELDS
        # =============================================

        required = self.REQUIRED_FIELDS.get(
            document_type,
            [],
        )

        for field in required:
            value = fields.get(field)

            if value is None or not str(value).strip():
                errors.append(
                    f"Missing required field: {field}"
                )

        # =============================================
        # STEP 3: EVIDENCE VALIDATION
        # =============================================

        for field, value in fields.items():

            if value is None or not str(value).strip():
                continue

            normalized_value = self.normalize_text(value)

            if normalized_value not in normalized_ocr:
                warnings.append(
                    f"Extracted value is not found "
                    f"verbatim in OCR: {field}"
                )

            evidence_text = evidence.get(field, "")

            if (
                not evidence_text
                or self.normalize_text(evidence_text)
                not in normalized_ocr
            ):
                warnings.append(
                    f"Missing or unverifiable "
                    f"OCR evidence: {field}"
                )

        # =============================================
        # STEP 4: DATE VALIDATION
        # =============================================

        for field in self.DATE_FIELDS:

            value = fields.get(field)

            if value and not self.parse_date(str(value)):
                errors.append(
                    f"Invalid date format or value: {field}"
                )

        # =============================================
        # STEP 5: AMOUNT VALIDATION
        # =============================================

        amounts: dict[str, Decimal] = {}

        for field in self.AMOUNT_FIELDS:

            value = fields.get(field)

            if value is None or not str(value).strip():
                continue

            amount = self.parse_amount(str(value))

            if amount is None:
                errors.append(
                    f"Invalid or ambiguous amount: {field}"
                )
            elif amount < 0:
                warnings.append(
                    f"Negative amount requires review: {field}"
                )
                amounts[field] = amount
            else:
                amounts[field] = amount

        # =============================================
        # STEP 6: ARITHMETIC CONSISTENCY
        # =============================================

        if all(
            field in amounts
            for field in ("subtotal", "tax", "total")
        ):

            expected_total = (
                amounts["subtotal"]
                + amounts["tax"]
            )

            actual_total = amounts["total"]

            difference = abs(
                expected_total - actual_total
            )

            if difference > Decimal("0.02"):
                errors.append(
                    "Total mismatch: "
                    f"subtotal + tax = {expected_total}, "
                    f"but total = {actual_total}"
                )

        # =============================================
        # STEP 7: REVIEW DECISION
        # =============================================

        # Warnings also trigger human review until
        # the corresponding evidence is verified.
        validation_passed = (
            len(errors) == 0
            and len(warnings) == 0
        )

        return {
            "validation_passed": validation_passed,
            "validation_errors": errors,
            "validation_warnings": warnings,
            "requires_review": not validation_passed,
            "agent_history": (
                state.get("agent_history", [])
                + ["validation_agent"]
            ),
        }

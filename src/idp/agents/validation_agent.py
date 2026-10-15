
from datetime import datetime
import re
from decimal import Decimal
from typing import Any

from idp.agents.state import DocumentState
from idp.utils.money import parse_money
from idp.utils.evidence import normalize_evidence, normalize_ocr_text

class ValidationAgent:

    OPTIONAL_FIELDS = {
        "invoice": ["tax_id", "iban", "subtotal", "tax", "po_reference"],
        "purchase_order": ["buyer", "bill_to", "ship_to", "total"],
        "receipt": ["receipt_number", "subtotal", "tax", "payment_method"],
        "contract": ["contract_number", "expiration_date", "contract_value", "governing_law"],
    }

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
            "seller",
            "issue_date",
            "total",
        ],
        # Missing agreement metadata requires review.
        "contract": ["contract_title", "party_a", "party_b", "effective_date"],
    }

    DATE_FIELDS = {
        "issue_date",
        "order_date",
        "effective_date",
        "expiration_date",
    }

    AMOUNT_FIELDS = {
        "subtotal",
        "tax",
        "total",
        "contract_value",
    }

    @staticmethod
    def normalize_text(value: Any) -> str:
        return normalize_ocr_text(value)

    @staticmethod
    def date_value(value: str):
        formats = (
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%m-%d-%Y",
            "%d %B %Y",
            "%B %d, %Y",
            "%d %b %Y",
        )

        for fmt in formats:
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue

        return None

    @classmethod
    def parse_date(cls, value: str) -> bool:
        return cls.date_value(value) is not None

    @staticmethod
    def parse_amount(value: str) -> Decimal | None:
        money = parse_money(value)

        if money is None:
            return None

        return money.amount

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

        # The baseline certifies a seller block only for a unique explicit
        # two-column layout. Text occurrence alone cannot establish field roles.
        baseline = state.get('baseline_fields', {})
        certificate = baseline.get('seller_tax_id_evidence') or ''
        certificate_parts = [self.normalize_text(part) for part in certificate.splitlines() if part.strip()]
        certified_seller = baseline.get('seller')
        certified_tax_id = baseline.get('tax_id')
        certified = (
            document_type == state.get('baseline_document_type') == 'invoice'
            and certified_seller and certified_tax_id and len(certificate_parts) == 3
            and certificate_parts[0] == 'seller:'
            and certificate_parts[1] == self.normalize_text(certified_seller)
            and self.normalize_text(certified_tax_id) in certificate_parts[2]
            and all(part in normalized_ocr for part in certificate_parts)
        )
        if certified:
            if fields.get('seller') and self.normalize_text(fields['seller']) != self.normalize_text(certified_seller):
                errors.append('Seller role conflicts with the layout-certified seller block.')
            if fields.get('tax_id') and self.normalize_text(fields['tax_id']) != self.normalize_text(certified_tax_id):
                errors.append('Seller tax ID conflicts with the layout-certified seller block.')

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
        required = sorted(set(required) | set(state.get('policy_config', {}).get('mandatory_fields', {}).get(document_type, [])))
        if document_type == 'invoice' and state.get('policy_config', {}).get('require_po_reference'):
            required.append('po_reference')
        if document_type == 'contract' and state.get('policy_config', {}).get('require_contract_expiration'):
            required.append('expiration_date')

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

            # The extracted value itself should be
            # traceable to the OCR text.
            if normalized_value not in normalized_ocr:
                warnings.append(
                    f"Extracted value is not found in OCR: {field}"
                )

            evidence_text = normalize_evidence(evidence.get(field, ""))

            if not evidence_text:
                warnings.append(
                    f"Missing OCR evidence: {field}"
                )
                continue

            # First attempt: verify the complete evidence.
            normalized_evidence = self.normalize_text(
                evidence_text
            )

            if normalized_evidence in normalized_ocr:
                continue

            # Second attempt: handle non-contiguous
            # label/value evidence in OCR tables.
            evidence_lines = [
                self.normalize_text(line)
                for line in evidence_text.splitlines()
                if line.strip()
            ]

            # Accept split evidence only when:
            # 1. The evidence has multiple components.
            # 2. Every component appears in OCR.
            # 3. The extracted value also appears in OCR.
            #
            # This verifies textual presence, not that
            # the label/value association is correct.
            split_evidence_found = (
                len(evidence_lines) >= 2
                and normalized_value in normalized_ocr
                and all(
                    part in normalized_ocr
                    for part in evidence_lines
                )
            )

            if not split_evidence_found:
                warnings.append(
                    f"Missing or unverifiable OCR evidence: {field}"
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

            if difference > Decimal(str(state.get('policy_config', {}).get('arithmetic_tolerance', '0.02'))):
                errors.append(
                    "Total mismatch: "
                    f"subtotal + tax = {expected_total}, "
                    f"but total = {actual_total}"
                )

        if document_type == "contract":
            parties = state.get("contract_parties", [])
            normalized_parties = [self.normalize_text(party) for party in parties]
            selected = [self.normalize_text(fields.get(role) or "") for role in ("party_a", "party_b")]
            if (len(parties) != 2 or len(set(normalized_parties)) != 2
                    or set(normalized_parties) != set(selected)
                    or any(party not in normalized_ocr for party in normalized_parties)):
                errors.append("Contract requires a complete, OCR-supported list of exactly two distinct parties.")
            if state.get("unsupported_contract_reasons"):
                errors.append("Unsupported contract structure requires manual review.")
            if re.search(r"\b(?:amendment|addendum)\b", str(fields.get("contract_title") or ""), re.I):
                errors.append("Contract amendment/addendum requires the underlying agreement and manual review.")
            if re.search(r"\bparty\s*(?:c|3|three)\s*[:(]|\bthird\s+party\s*:", ocr_text, re.I):
                errors.append("Additional contracting party cannot be represented by the two-party schema.")
            party_a = self.normalize_text(fields.get("party_a") or "")
            party_b = self.normalize_text(fields.get("party_b") or "")
            if party_a and party_a == party_b:
                errors.append("Contract parties must be distinct.")
            start = self.date_value(str(fields.get("effective_date") or ""))
            end = self.date_value(str(fields.get("expiration_date") or ""))
            if start and end and end < start:
                errors.append("Contract expiration date precedes effective date.")

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
            "missing_optional_fields": [field for field in self.OPTIONAL_FIELDS.get(document_type, []) if field not in required and not fields.get(field)],
            "validation_passed": validation_passed,
            "validation_errors": errors,
            "validation_warnings": warnings,
            "requires_review": not validation_passed,
            "agent_history": (
                state.get("agent_history", [])
                + ["validation_agent"]
            ),
        }

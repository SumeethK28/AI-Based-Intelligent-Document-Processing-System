
import re
from decimal import Decimal

from idp.agents.validation_agent import ValidationAgent
from idp.storage.repository import DocumentRepository


class CrossDocumentVerifier:

    def __init__(
        self,
        repository: DocumentRepository,
    ):
        self.repository = repository
        self.validator = ValidationAgent()

    @staticmethod
    def normalize_name(value: str | None) -> str:
        return " ".join(
            str(value or "").casefold().split()
        )

    @staticmethod
    def currency(value: str | None) -> str | None:
        """
        Only recognize explicit currency symbols.
        Unknown currency is not assumed to match.
        """
        if not value:
            return None

        symbols = {
            "₹": "INR",
            "$": "USD",
            "€": "EUR",
            "£": "GBP",
        }

        found = {
            currency
            for symbol, currency in symbols.items()
            if symbol in value
        }

        return next(iter(found)) if len(found) == 1 else None

    @staticmethod
    def issue(
        code: str,
        description: str,
        severity: str = "medium",
    ) -> dict:
        return {
            "code": code,
            "description": description,
            "severity": severity,
        }

    def verify(self, state: dict) -> dict:

        document_type = state.get(
            "document_type",
            "unknown",
        )

        fields = state.get(
            "extracted_fields",
            {},
        )

        # Currently verify invoices against stored POs.
        if document_type != "invoice":
            return {
                "cross_document_status": "not_applicable",
                "cross_document_issues": [],
                "matched_document_id": None,
            }

        po_reference = fields.get("po_reference")

        if not po_reference:
            return {
                "cross_document_status": "not_checked",
                "cross_document_issues": [],
                "matched_document_id": None,
            }

        candidates = self.repository.find_purchase_orders(
            str(po_reference)
        )

        if not candidates:
            return {
                "cross_document_status": "unmatched",
                "cross_document_issues": [
                    self.issue(
                        "PO_NOT_FOUND",
                        f"No stored Purchase Order matches "
                        f"reference {po_reference}.",
                    )
                ],
                "matched_document_id": None,
            }

        if len(candidates) > 1:
            return {
                "cross_document_status": "ambiguous",
                "cross_document_issues": [
                    self.issue(
                        "MULTIPLE_PO_MATCHES",
                        "Multiple stored Purchase Orders "
                        "share this reference.",
                    )
                ],
                "matched_document_id": None,
            }

        po = candidates[0]
        po_fields = po["extracted_fields"]

        issues = []
        incomplete_checks = []

        # ---------------------------------------------
        # Vendor / seller comparison
        # ---------------------------------------------

        invoice_seller = self.normalize_name(
            fields.get("seller")
        )

        po_vendor = self.normalize_name(
            po_fields.get("vendor")
        )

        if invoice_seller and po_vendor:

            if invoice_seller != po_vendor:
                issues.append(
                    self.issue(
                        "VENDOR_MISMATCH",
                        "Invoice seller does not match "
                        "Purchase Order vendor.",
                    )
                )

        else:
            incomplete_checks.append(
                "Vendor comparison was not possible."
            )

        # ---------------------------------------------
        # Total comparison
        # ---------------------------------------------

        invoice_total_text = fields.get("total")
        po_total_text = po_fields.get("total")

        invoice_total = (
            self.validator.parse_amount(
                invoice_total_text
            )
            if invoice_total_text else None
        )

        po_total = (
            self.validator.parse_amount(
                po_total_text
            )
            if po_total_text else None
        )

        invoice_currency = self.currency(
            invoice_total_text
        )

        po_currency = self.currency(
            po_total_text
        )

        if (
            invoice_total is not None
            and po_total is not None
            and invoice_currency is not None
            and invoice_currency == po_currency
        ):

            difference = invoice_total - po_total

            if abs(difference) > Decimal("0.02"):
                issues.append(
                    self.issue(
                        "TOTAL_MISMATCH",
                        (
                            f"Invoice total {invoice_total} "
                            f"differs from PO total {po_total} "
                            f"by {difference:+} "
                            f"{invoice_currency}."
                        ),
                    )
                )

        else:
            incomplete_checks.append(
                "Totals could not be safely compared "
                "because amounts or currency information "
                "were missing or incompatible."
            )

        # ---------------------------------------------
        # Decision
        # ---------------------------------------------

        if issues:
            status = "mismatch"

        elif incomplete_checks:
            status = "incomplete"

        else:
            status = "matched"

        return {
            "cross_document_status": status,
            "cross_document_issues": (
                issues
                + [
                    self.issue(
                        "INCOMPLETE_COMPARISON",
                        message,
                        "low",
                    )
                    for message in incomplete_checks
                ]
            ),
            "matched_document_id": po["document_id"],
        }

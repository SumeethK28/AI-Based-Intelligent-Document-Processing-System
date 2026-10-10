
from decimal import Decimal
from typing import Any

from idp.storage.repository import DocumentRepository
from idp.utils.money import parse_money


class CrossDocumentVerifier:
    """
    Verifies an invoice against a previously stored
    Purchase Order using:

    1. Purchase Order reference matching
    2. Vendor / seller consistency
    3. Currency consistency
    4. Total amount consistency

    Returns the verification status, detected issues,
    and the matched Purchase Order document ID.
    """

    def __init__(
        self,
        repository: DocumentRepository,
    ):
        self.repository = repository

    # ========================================================
    # NORMALIZE COMPANY / PERSON NAMES
    # ========================================================

    @staticmethod
    def normalize_name(value: str | None) -> str:
        """
        Normalize names for case-insensitive comparison.

        Example:
            "ABC Technologies"
            "abc technologies"

        Both become:
            "abc technologies"
        """
        return " ".join(
            str(value or "").casefold().split()
        )

    # ========================================================
    # CREATE VERIFICATION ISSUE
    # ========================================================

    @staticmethod
    def issue(
        code: str,
        description: str,
        severity: str = "medium",
    ) -> dict[str, str]:
        return {
            "code": code,
            "description": description,
            "severity": severity,
        }

    # ========================================================
    # VERIFY DOCUMENT
    # ========================================================

    def verify(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any]:

        document_type = state.get(
            "document_type",
            "unknown",
        )

        fields = state.get(
            "extracted_fields",
            {},
        )

        # ----------------------------------------------------
        # STEP 1: CHECK DOCUMENT TYPE
        # ----------------------------------------------------

        # Currently, cross-document verification checks
        # invoices against previously stored purchase orders.

        if document_type != "invoice":

            return {
                "cross_document_status": "not_applicable",
                "cross_document_issues": [],
                "matched_document_id": None,
            }

        # ----------------------------------------------------
        # STEP 2: EXTRACT PURCHASE ORDER REFERENCE
        # ----------------------------------------------------

        po_reference = fields.get(
            "po_reference"
        )

        if not po_reference:

            return {
                "cross_document_status": "not_checked",
                "cross_document_issues": [],
                "matched_document_id": None,
            }

        # ----------------------------------------------------
        # STEP 3: SEARCH SQLITE DATABASE
        # ----------------------------------------------------

        candidates = (
            self.repository.find_purchase_orders(
                str(po_reference)
            )
        )

        # No purchase order exists with this reference.

        if not candidates:

            return {
                "cross_document_status": "unmatched",
                "cross_document_issues": [
                    self.issue(
                        code="PO_NOT_FOUND",
                        description=(
                            "No stored Purchase Order matches "
                            f"reference {po_reference}."
                        ),
                    )
                ],
                "matched_document_id": None,
            }

        # Multiple stored purchase orders have the same
        # PO number. Do not select one arbitrarily.

        if len(candidates) > 1:

            return {
                "cross_document_status": "ambiguous",
                "cross_document_issues": [
                    self.issue(
                        code="MULTIPLE_PO_MATCHES",
                        description=(
                            "Multiple stored Purchase Orders "
                            "share this reference."
                        ),
                    )
                ],
                "matched_document_id": None,
            }

        # ----------------------------------------------------
        # STEP 4: RETRIEVE MATCHED PURCHASE ORDER
        # ----------------------------------------------------

        po = candidates[0]

        po_fields = po[
            "extracted_fields"
        ]

        issues: list[dict[str, str]] = []

        incomplete_checks: list[str] = []

        # ====================================================
        # STEP 5: COMPARE VENDOR / SELLER
        # ====================================================

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
                        code="VENDOR_MISMATCH",
                        description=(
                            "Invoice seller does not match "
                            "Purchase Order vendor. "
                            f"Invoice: {fields.get('seller')}; "
                            f"Purchase Order: "
                            f"{po_fields.get('vendor')}."
                        ),
                    )
                )

        else:

            incomplete_checks.append(
                "Vendor comparison was not possible "
                "because seller or vendor information "
                "was missing."
            )

        # ====================================================
        # STEP 6: PARSE TOTALS AND CURRENCIES
        # ====================================================

        invoice_money = parse_money(
            fields.get("total")
        )

        po_money = parse_money(
            po_fields.get("total")
        )

        # ----------------------------------------------------
        # CASE A: INVALID OR MISSING AMOUNT
        # ----------------------------------------------------

        if (
            invoice_money is None
            or po_money is None
        ):

            incomplete_checks.append(
                "One or both document totals could "
                "not be parsed."
            )

        # ----------------------------------------------------
        # CASE B: MISSING CURRENCY
        # ----------------------------------------------------

        elif (
            invoice_money.currency is None
            or po_money.currency is None
        ):

            incomplete_checks.append(
                "Currency information is missing "
                "from one or both document totals."
            )

        # ----------------------------------------------------
        # CASE C: DIFFERENT CURRENCIES
        # ----------------------------------------------------

        elif (
            invoice_money.currency
            != po_money.currency
        ):

            issues.append(
                self.issue(
                    code="CURRENCY_MISMATCH",
                    description=(
                        "Invoice and Purchase Order use "
                        "different currencies. "
                        f"Invoice: {invoice_money.currency}; "
                        f"Purchase Order: {po_money.currency}."
                    ),
                )
            )

        # ----------------------------------------------------
        # CASE D: SAME CURRENCY — COMPARE AMOUNTS
        # ----------------------------------------------------

        else:

            difference = (
                invoice_money.amount
                - po_money.amount
            )

            tolerance = Decimal("0.02")

            if abs(difference) > tolerance:

                issues.append(
                    self.issue(
                        code="TOTAL_MISMATCH",
                        description=(
                            f"Invoice total "
                            f"{invoice_money.amount} "
                            f"differs from Purchase Order total "
                            f"{po_money.amount} "
                            f"by {difference:+} "
                            f"{invoice_money.currency}."
                        ),
                    )
                )

        # ====================================================
        # STEP 7: DETERMINE VERIFICATION STATUS
        # ====================================================

        if issues:

            status = "mismatch"

        elif incomplete_checks:

            status = "incomplete"

        else:

            status = "matched"

        # ====================================================
        # STEP 8: CONVERT INCOMPLETE CHECKS INTO ISSUES
        # ====================================================

        for message in incomplete_checks:

            issues.append(
                self.issue(
                    code="INCOMPLETE_COMPARISON",
                    description=message,
                    severity="low",
                )
            )

        # ====================================================
        # STEP 9: RETURN RESULTS
        # ====================================================

        return {
            "cross_document_status": status,
            "cross_document_issues": issues,
            "matched_document_id": po["document_id"],
        }

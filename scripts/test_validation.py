"""Validation component tests with grounded and deliberately invalid fields."""
import unittest
from idp.agents.validation_agent import ValidationAgent
from idp.models.invoice import InvoiceData
from idp.models.purchase_order import PurchaseOrderData
from idp.validation.invoice_validator import InvoiceValidator
from idp.validation.purchase_order_validator import PurchaseOrderValidator


class ValidationTests(unittest.TestCase):
    def validate(self, fields, kind="invoice"):
        return ValidationAgent().run({"document_type": kind, "extracted_fields": fields,
                                      "ocr_text": "\n".join(fields.values()), "field_evidence": fields})

    def test_invoice_arithmetic_and_invalid_date(self):
        fields = {"invoice_number": "INV-1", "issue_date": "2026-10-10", "seller": "Acme", "client": "Buyer",
                  "subtotal": "INR 100.00", "tax": "INR 10.00", "total": "INR 110.00"}
        self.assertTrue(self.validate(fields)["validation_passed"])
        result = self.validate({**fields, "total": "INR 120.00", "issue_date": "2026-02-30"})
        self.assertFalse(result["validation_passed"])
        self.assertTrue(any("Total mismatch" in error for error in result["validation_errors"]))
        self.assertTrue(any("Invalid date" in error for error in result["validation_errors"]))

    def test_missing_fields_unknown_types_and_negative_amount(self):
        for kind in ("invoice", "receipt", "contract", "purchase_order", "unknown"):
            with self.subTest(kind=kind):
                self.assertFalse(self.validate({}, kind)["validation_passed"])
        result = self.validate({"seller": "Shop", "issue_date": "2026-10-10", "total": "-20.00"}, "receipt")
        self.assertTrue(result["requires_review"])
        self.assertTrue(result["validation_warnings"])

    def test_contract_distinct_parties_and_dates(self):
        fields = {"contract_title": "Agreement", "party_a": "Acme", "party_b": "Buyer", "effective_date": "2026-10-10"}
        self.assertTrue(self.validate(fields, "contract")["validation_passed"])
        self.assertFalse(self.validate({**fields, "party_b": "Acme"}, "contract")["validation_passed"])
        self.assertFalse(self.validate({**fields, "expiration_date": "2025-10-10"}, "contract")["validation_passed"])

    def test_hallucinated_values_and_evidence_require_review(self):
        result = ValidationAgent().run({"document_type": "receipt", "extracted_fields": {"seller": "Invented", "total": "20.00"},
                                        "ocr_text": "Shop 20.00", "field_evidence": {"seller": "Invented"}})
        self.assertFalse(result["validation_passed"])
        self.assertTrue(result["validation_warnings"])

    def test_baseline_validators(self):
        invoice = InvoiceData(invoice_number="INV-1", issue_date="10/10/2026", seller="Acme", client="Buyer", total="$20.00")
        self.assertTrue(InvoiceValidator().validate(invoice).is_valid)
        invoice.issue_date = "30/02/2026"
        self.assertFalse(InvoiceValidator().validate(invoice).is_valid)
        po = PurchaseOrderData(po_number="PO-1", order_date="10/10/2026", vendor="Acme", total="20.00")
        self.assertTrue(PurchaseOrderValidator().validate(po).is_valid)
        po.total = "invalid"
        self.assertFalse(PurchaseOrderValidator().validate(po).is_valid)


if __name__ == "__main__":
    unittest.main()

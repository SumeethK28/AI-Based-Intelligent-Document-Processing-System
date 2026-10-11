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

    def test_optional_omissions_are_not_mandatory_failures(self):
        result = self.validate({"invoice_number": "INV-1", "issue_date": "2026-10-10", "seller": "Acme", "client": "Buyer", "total": "20.00"})
        self.assertTrue(result["validation_passed"])
        self.assertIn("tax_id", result["missing_optional_fields"])
        self.assertEqual(result["validation_errors"], [])

    def test_currency_spacing_and_ocr_backed_currency(self):
        from idp.agents.extraction_agent import ExtractionAgent
        from idp.llm.schemas import AIExtractionResult
        from unittest.mock import Mock
        llm = Mock()
        llm.generate_structured.return_value = AIExtractionResult(confidence=1, seller="Shop", issue_date="2026-10-10", total="$819,06", subtotal="744,60",
                                                                field_evidence={"seller": "Shop", "issue_date": "2026-10-10", "total": "$819,06", "subtotal": "744,60"})
        state = {"document_type": "receipt", "ocr_text": "Shop\n2026-10-10\n$ 819,06\n$744,60"}
        result = ExtractionAgent(llm).run(state)
        self.assertEqual(result["extracted_fields"]["subtotal"], "$744,60")
        self.assertEqual(result["evidence_warnings"], [])
        self.assertTrue(ValidationAgent().run({**state, **result})["validation_passed"])
        state["ocr_text"] += "\nEUR 744,60"
        self.assertEqual(ExtractionAgent(llm).run(state)["extracted_fields"]["subtotal"], "744,60")

    def test_router_blocks_unresolved_issues_even_with_stale_review_flag(self):
        from idp.agents.routing_agent import WorkflowRoutingAgent
        state = {"document_type": "invoice", "validation_passed": True, "requires_review": False, "risk_level": "low"}
        for status in ("unmatched", "ambiguous", "mismatch", "incomplete"):
            self.assertEqual(WorkflowRoutingAgent().run({**state, "cross_document_status": status})["workflow_status"], "manual_review")
        self.assertEqual(WorkflowRoutingAgent().run({**state, "validation_passed": False})["workflow_status"], "manual_review")

    def test_bounded_api_retries(self):
        import httpx
        from groq import APIStatusError, APIConnectionError
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from idp.llm.provider import GroqProvider
        request = httpx.Request("POST", "https://api.groq.com/test")
        for status in (400, 401, 403, 429, 500, 503):
            response = httpx.Response(status, request=request)
            error = APIStatusError("test failure", response=response, body=None)
            create = Mock(side_effect=error)
            provider = GroqProvider.__new__(GroqProvider)
            provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            with patch("idp.llm.provider.time.sleep") as sleep:
                with self.assertRaises(APIStatusError):
                    provider._request()
                self.assertEqual(create.call_count, 3 if status >= 429 else 1)
                self.assertEqual(sleep.call_count, 2 if status >= 429 else 0)
        create = Mock(side_effect=[APIConnectionError(request=request), "success"])
        provider.client.chat.completions.create = create
        with patch("idp.llm.provider.time.sleep"):
            self.assertEqual(provider._request(), "success")
        response = httpx.Response(429, request=request, headers={"retry-after": "60"})
        create.side_effect = APIStatusError("test failure", response=response, body=None)
        create.reset_mock()
        with patch("idp.llm.provider.time.sleep") as sleep:
            with self.assertRaises(APIStatusError):
                provider._request()
            self.assertEqual(create.call_count, 1)
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()

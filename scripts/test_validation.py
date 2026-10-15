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
                                      "ocr_text": "\n".join(fields.values()), "field_evidence": fields,
                                      "contract_parties": [fields[role] for role in ("party_a", "party_b") if fields.get(role)]})

    def test_contract_incomplete_and_unsupported_structure(self):
        fields = {"contract_title": "Agreement", "party_a": "Acme", "party_b": "Buyer", "effective_date": "2026-10-10"}
        state = {"document_type": "contract", "extracted_fields": fields,
                 "ocr_text": "\n".join(fields.values()), "field_evidence": fields}
        self.assertFalse(ValidationAgent().run(state)["validation_passed"])
        state["contract_parties"] = ["Acme", "Buyer", "Third Company"]
        self.assertFalse(ValidationAgent().run(state)["validation_passed"])
        state["contract_parties"] = ["Acme", "Buyer"]
        state["unsupported_contract_reasons"] = ["Amendment depends on unavailable agreement"]
        self.assertFalse(ValidationAgent().run(state)["validation_passed"])
        state["unsupported_contract_reasons"] = []
        state["ocr_text"] += "\nParty C: Third Company"
        self.assertFalse(ValidationAgent().run(state)["validation_passed"])

    def test_explicit_third_contract_party_is_preserved(self):
        from unittest.mock import Mock
        from idp.agents.extraction_agent import ExtractionAgent
        from idp.llm.schemas import AIExtractionResult
        fields = {"contract_title": "Services Agreement", "party_a": "Acme", "party_b": "Buyer", "effective_date": "2026-10-10"}
        llm = Mock()
        llm.generate_structured.return_value = AIExtractionResult(**fields, confidence=1, field_evidence=fields, contract_parties=["Acme", "Buyer"])
        state = {"document_type": "contract", "ocr_text": "\n".join(fields.values()) + "\nParty C: Third Company"}
        result = ExtractionAgent(llm).run(state)
        self.assertEqual(result["contract_parties"], ["Acme", "Buyer", "Third Company"])
        self.assertFalse(ValidationAgent().run({**state, **result})["validation_passed"])
        result["contract_parties"] = ["Acme", "Buyer"]
        result["unsupported_contract_reasons"] = []
        state["ocr_text"] = "\n".join(fields.values()) + "\nAmendment"
        result["extracted_fields"]["contract_title"] = "Amendment"
        self.assertFalse(ValidationAgent().run({**state, **result})["validation_passed"])

    def test_seller_tax_id_uses_layout_not_text_order(self):
        from dataclasses import asdict
        from unittest.mock import Mock
        from idp.extraction.invoice_extractor import InvoiceExtractor
        from idp.models.ocr import OCRRegion
        from idp.agents.extraction_agent import ExtractionAgent
        from idp.llm.schemas import AIExtractionResult
        def region(text, x, y, width=150):
            return OCRRegion(text, 1, [[x, y], [x + width, y], [x + width, y + 20], [x, y + 20]])
        # Seller is on the right, and the client's ID occurs first in OCR.
        regions = [region("Client:", 10, 10), region("Seller:", 500, 10),
                   region("Buyer LLC", 10, 40), region("Acme Ltd", 500, 40),
                   region("Tax Id: 901-88-0463", 10, 100), region("Tax Id: 909-83-7738", 500, 100)]
        text = "\n".join(r.text for r in regions)
        baseline = asdict(InvoiceExtractor().extract(text, regions))
        self.assertEqual(baseline["tax_id"], "909-83-7738")
        llm = Mock()
        llm.generate_structured.return_value = AIExtractionResult(confidence=1, seller="Acme Ltd", total="118.00",
                                                                 field_evidence={"seller": "Acme Ltd", "total": "118.00"})
        state = {"document_type": "invoice", "baseline_document_type": "invoice", "baseline_fields": {**baseline, "total": "999.00"}, "ocr_text": text + "\n118.00"}
        result = ExtractionAgent(llm).run(state)
        self.assertEqual(result["extracted_fields"]["tax_id"], "909-83-7738")
        self.assertEqual(result["extracted_fields"]["total"], "118.00")
        self.assertIn("Seller:", result["field_evidence"]["tax_id"])
        self.assertEqual(result["evidence_warnings"], [])
        llm.generate_structured.return_value.tax_id = "909-83-7738"
        self.assertNotIn("tax_id", ExtractionAgent(llm).run(state)["fallback_used"])
        llm.generate_structured.return_value.tax_id = None
        for ambiguous in ([], regions + [region("Tax Id: OTHER-ID", 500, 130)], regions + [region("Seller:", 500, 10)]):
            state["baseline_fields"] = asdict(InvoiceExtractor().extract(text, ambiguous))
            self.assertNotIn("tax_id", ExtractionAgent(llm).run(state)["extracted_fields"])
        state["baseline_fields"] = baseline
        llm.generate_structured.return_value.seller = "Buyer LLC"
        self.assertNotIn("tax_id", ExtractionAgent(llm).run(state)["extracted_fields"])

    def test_invoice_arithmetic_and_invalid_date(self):
        fields = {"invoice_number": "INV-1", "issue_date": "2026-10-10", "seller": "Acme", "client": "Buyer",
                  "subtotal": "INR 100.00", "tax": "INR 10.00", "total": "INR 110.00"}
        self.assertTrue(self.validate(fields)["validation_passed"])
        result = self.validate({**fields, "total": "INR 120.00", "issue_date": "2026-02-30"})
        self.assertFalse(result["validation_passed"])
        self.assertTrue(any("Total mismatch" in error for error in result["validation_errors"]))
        self.assertTrue(any("Invalid date" in error for error in result["validation_errors"]))

    def test_layout_certified_role_conflicts_require_review_without_overwriting(self):
        import copy
        from idp.agents.routing_agent import WorkflowRoutingAgent
        fields={'invoice_number':'INV-ROLE','issue_date':'2026-10-14','seller':'Acme Ltd','client':'Buyer LLC','total':'INR 118.00','tax_id':'901-88-0463'}
        text='\n'.join(fields.values())+'\nSeller:\nAcme Ltd\nTax Id: 909-83-7738'
        state={'document_type':'invoice','baseline_document_type':'invoice','extracted_fields':fields,
            'ocr_text':text,'field_evidence':dict(fields),'agent_history':[],
            'baseline_fields':{'seller':'Acme Ltd','tax_id':'909-83-7738','total':'999.00',
                'seller_tax_id_evidence':'Seller:\nAcme Ltd\nTax Id: 909-83-7738'}}
        original=copy.deepcopy(fields)
        result=ValidationAgent().run(state)
        self.assertFalse(result['validation_passed'])
        self.assertTrue(any('Seller tax ID conflicts' in error for error in result['validation_errors']))
        self.assertEqual(WorkflowRoutingAgent().run({**state,**result,'risk_level':'low'})['workflow_status'],'manual_review')
        self.assertEqual(fields,original)
        fields['seller']='Buyer LLC'
        self.assertTrue(any('Seller role conflicts' in error for error in ValidationAgent().run(state)['validation_errors']))

    def test_layout_certificate_preserves_correct_or_missing_optional_tax_id(self):
        fields={'invoice_number':'INV-ROLE','issue_date':'2026-10-14','seller':'Acme Ltd','client':'Buyer LLC','total':'INR 118.00','tax_id':'909-83-7738'}
        state={'document_type':'invoice','baseline_document_type':'invoice','extracted_fields':fields,
            'ocr_text':'\n'.join(fields.values())+'\nSeller:\nAcme Ltd\nTax Id: 909-83-7738',
            'field_evidence':dict(fields),'baseline_fields':{'seller':'Acme Ltd','tax_id':'909-83-7738',
                'seller_tax_id_evidence':'Seller:\nAcme Ltd\nTax Id: 909-83-7738'}}
        self.assertTrue(ValidationAgent().run(state)['validation_passed'])
        fields.pop('tax_id')
        result=ValidationAgent().run(state)
        self.assertTrue(result['validation_passed'])
        self.assertIn('tax_id',result['missing_optional_fields'])
        fields['tax_id']='901-88-0463';state['ocr_text']+='\n901-88-0463';state['field_evidence']['tax_id']='901-88-0463'
        state['baseline_fields']['seller_tax_id_evidence']='Seller:\nAcme Ltd\nFabricated Tax Id: 909-83-7738'
        self.assertTrue(ValidationAgent().run(state)['validation_passed'])

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

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from idp.llm.schemas import AIClassificationResult, AIExtractionResult
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
from idp.agents.validation_agent import ValidationAgent
from idp.agents.cross_document_agent import CrossDocumentAgent
from idp.extraction.receipt_extractor import ReceiptExtractor


class FakeLLM:
    def __init__(self):
        self.kind = "purchase_order"
        self.fields = {}
        self.calls = 0

    def generate_structured(self, *, response_model, **kwargs):
        self.calls += 1
        if response_model is AIClassificationResult:
            return response_model(document_type=self.kind, confidence=1)
        return AIExtractionResult(**self.fields, confidence=1, field_evidence=self.fields,
                                  contract_parties=[self.fields[role] for role in ("party_a", "party_b") if self.fields.get(role)])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.llm = FakeLLM()
        self.baseline = SimpleNamespace(process=self.baseline_result)
        self.pipeline = AgenticDocumentPipeline(self.root / "test.db", baseline=self.baseline, llm=self.llm)

    def baseline_result(self, path):
        return SimpleNamespace(extracted_data=None, classification=SimpleNamespace(document_class=SimpleNamespace(value=self.llm.kind)), ocr=SimpleNamespace(full_text="\n".join(self.llm.fields.values()), average_confidence=1))

    def process(self, name, kind, fields):
        self.llm.kind, self.llm.fields = kind, fields
        path = self.root / name
        path.write_text(name)
        return self.pipeline.process(path)

    def test_invoice_po_duplicate_and_reprocessing(self):
        po = self.process("po.txt", "purchase_order", {"po_number": "PO-1", "order_date": "2026-10-01", "vendor": "Acme", "total": "INR 110.00"})
        invoice = {"invoice_number": "INV-1", "issue_date": "2026-10-02", "seller": "Acme", "client": "Buyer", "subtotal": "INR 100.00", "tax": "INR 10.00", "total": "INR 110.00", "po_reference": "PO-1"}
        result = self.process("invoice.txt", "invoice", invoice)
        self.assertEqual(result["state"]["cross_document_status"], "matched")
        self.assertEqual(result["state"]["matched_document_id"], po["document_id"])
        self.assertEqual(result["state"]["agent_history"][-3:], ["cross_document_verification", 'business_policy', "routing_agent"])
        self.assertEqual(result["state"]["assigned_department"], "Finance")
        calls = self.llm.calls
        duplicate = self.pipeline.process(self.root / "invoice.txt")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(self.llm.calls, calls)
        self.pipeline.repository.update_review(result["document_id"], "approved",'Simulated verified review',expected_revision=self.pipeline.repository.get_document(result['document_id'])['revision'])
        self.llm.fields = {**invoice, "total": "INR 120.00"}
        updated = self.pipeline.process(self.root / "invoice.txt", force_reprocess=True)
        self.assertTrue(updated["reprocessed"])
        self.assertEqual(updated["document_id"], result["document_id"])
        self.assertEqual(updated["state"]["cross_document_status"], "mismatch")
        self.assertEqual(updated["state"]["workflow_status"], "manual_review")
        stored = self.pipeline.repository.get_document(result["document_id"])
        self.assertEqual(stored["review_decision"], "pending")
        self.assertEqual(stored["full_result"], updated["state"])
        self.assertEqual(len(self.pipeline.repository.list_documents()), 2)
        self.assertEqual(len(self.pipeline.repository.list_processing_runs()), 4)

    def test_receipt_and_contract(self):
        receipt = self.process("receipt.txt", "receipt", {"seller": "Shop", "issue_date": "2026-10-01", "total": "INR 20.00"})
        self.assertTrue(receipt["state"]["validation_passed"])
        self.assertEqual(receipt["state"]["assigned_department"], "Expense Processing")
        contract = self.process("contract.txt", "contract", {"contract_title": "Services Agreement", "party_a": "Acme", "party_b": "Buyer", "effective_date": "1 October 2026", "expiration_date": "2027-10-01"})
        self.assertTrue(contract["state"]["validation_passed"])
        self.assertEqual(contract["state"]["assigned_department"], "Legal")
        state = contract["state"]
        state["extracted_fields"]["expiration_date"] = "2025-10-01"
        self.assertFalse(ValidationAgent().run(state)["validation_passed"])
        self.assertFalse(ValidationAgent().run({"document_type": "contract"})["validation_passed"])
        parsed = ReceiptExtractor().extract("Merchant: Shop\nDate: 2026-10-01\nSubtotal: 10\nTotal: 11\nCash tendered: 20\nChange: 9")
        self.assertEqual(parsed.total, "11")

    def test_verification_preserves_high_risk(self):
        state = {"document_type": "invoice", "extracted_fields": {"po_reference": "missing"}, "risk_level": "high"}
        result = CrossDocumentAgent(self.pipeline.repository).run(state)
        self.assertEqual(result["risk_level"], "high")
        self.assertTrue(result["requires_review"])

    def test_cross_document_edge_cases(self):
        from idp.verification.cross_document import CrossDocumentVerifier
        verifier = CrossDocumentVerifier(self.pipeline.repository)
        po_fields = {"po_number": "PO-1", "order_date": "2026-10-01", "vendor": "Acme", "total": "INR 10.00"}
        self.process("first.txt", "purchase_order", po_fields)
        state = {"document_type": "invoice", "extracted_fields": {"po_reference": "PO-1", "seller": "Acme", "total": "USD 10.00"}}
        self.assertEqual(verifier.verify(state)["cross_document_issues"][0]["code"], "CURRENCY_MISMATCH")
        state["extracted_fields"]["total"] = "10.00"
        self.assertEqual(verifier.verify(state)["cross_document_status"], "incomplete")
        state["extracted_fields"]["seller"] = "Other"
        self.assertTrue(any(x["code"] == "VENDOR_MISMATCH" for x in verifier.verify(state)["cross_document_issues"]))
        self.process("second.txt", "purchase_order", po_fields)
        self.assertEqual(verifier.verify(state)["cross_document_status"], "ambiguous")

    def test_receipt_fallback_and_legacy_service(self):
        from idp.agents.extraction_agent import ExtractionAgent
        from idp.pipeline.agent_document_service import AgentDocumentService
        self.llm.fields = {}
        state = {"document_type": "receipt", "baseline_document_type": "receipt", "baseline_fields": {"merchant": "Shop", "date": "2026-10-01", "total": "INR 20.00"}, "ocr_text": "Shop 2026-10-01 INR 20.00"}
        extracted = ExtractionAgent(self.llm).run(state)
        self.assertEqual(extracted["extracted_fields"]["seller"], "Shop")
        self.assertFalse(extracted["evidence_warnings"])
        service = AgentDocumentService(self.root / "service.db", baseline=self.baseline, llm=self.llm)
        self.llm.kind = "receipt"
        self.llm.fields = {"seller": "Shop", "issue_date": "2026-10-01", "total": "INR 20.00"}
        path = self.root / "service.txt"
        path.write_text("service")
        self.assertFalse(service.process_document(path)["is_duplicate"])
        self.assertTrue(service.process_document(path)["is_duplicate"])
        self.assertTrue(service.process_document(path, force_reprocess=True)["reprocessed"])

    def test_escaped_evidence_separators(self):
        from idp.agents.extraction_agent import ExtractionAgent
        fields = {"seller": "Shop", "issue_date": "2026-10-01", "total": "INR 20.00"}
        class EvidenceLLM:
            def generate_structured(self, **kwargs):
                return AIExtractionResult(**fields, confidence=1, field_evidence={
                    "seller": r"Seller:\nShop", "issue_date": r"Date:\n2026-10-01", "total": r"Total:\nINR 20.00"})
        state = {"document_type": "receipt", "ocr_text": "Seller:\nShop\nDate:\n2026-10-01\nTotal:\nINR 20.00"}
        state.update(ExtractionAgent(EvidenceLLM()).run(state))
        self.assertEqual(state["evidence_warnings"], [])
        self.assertTrue(ValidationAgent().run(state)["validation_passed"])
        state["field_evidence"]["seller"] = r"Invented label:\nShop"
        self.assertFalse(ValidationAgent().run(state)["validation_passed"])

    def test_real_pdf_ocr_invoice_and_po(self):
        from reportlab.pdfgen import canvas
        from idp.ocr.rapidocr_engine import RapidOCREngine
        from idp.pipeline.document_pipeline import DocumentPipeline
        pipeline = DocumentPipeline(RapidOCREngine())
        for name, title, lines, identifier in (
            ("real_po.pdf", "PURCHASE ORDER", ["PO Number: PO-1023", "Vendor: ABC Technologies", "Order Date: 10/10/2026", "Total: INR 42000.00"], "po_number"),
            ("real_invoice.pdf", "INVOICE", ["Invoice Number: INV-501", "Seller: ABC Technologies", "Client: XYZ Company", "Issue Date: 10/10/2026", "Total: INR 42000.00"], "invoice_number"),
        ):
            path = self.root / name
            pdf = canvas.Canvas(str(path))
            pdf.setFont("Helvetica", 16)
            for index, line in enumerate([title] + lines):
                pdf.drawString(50, 780 - index * 40, line)
            pdf.save()
            result = pipeline.process(path)
            self.assertIn(title, result.ocr.full_text.upper())
            self.assertIsNotNone(result.extracted_data)
            self.assertTrue(getattr(result.extracted_data, identifier))
            self.assertIsNotNone(result.extracted_data.total)

    def test_streamlit_pages(self):
        from streamlit.testing.v1 import AppTest
        self.process("ui.txt", "receipt", {"seller": "Shop", "issue_date": "2026-10-01", "total": "INR 20.00"})
        with patch.dict("os.environ", {"IDP_DATABASE_PATH": str(self.pipeline.repository.db_path)}), patch("idp.pipeline.agentic_pipeline.AgenticDocumentPipeline", return_value=self.pipeline):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/app.py"), default_timeout=30).run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.radio(key="navigation").options), 9)
            self.assertGreater(len(app.selectbox), 0)



if __name__ == "__main__":
    unittest.main()


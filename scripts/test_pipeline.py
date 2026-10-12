"""Component regression tests; API responses are simulated unless explicitly noted."""
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
        return AIExtractionResult(**self.fields, confidence=1, field_evidence=self.fields)


from _test_support import PipelineFixture


class PipelineTests(PipelineFixture):

    def test_invoice_po_duplicate_and_reprocessing(self):
            po = self.process("po.txt", "purchase_order", {"po_number": "PO-1", "order_date": "2026-10-01", "vendor": "Acme", "total": "INR 110.00"})
            invoice = {"invoice_number": "INV-1", "issue_date": "2026-10-02", "seller": "Acme", "client": "Buyer", "subtotal": "INR 100.00", "tax": "INR 10.00", "total": "INR 110.00", "po_reference": "PO-1"}
            result = self.process("invoice.txt", "invoice", invoice)
            self.assertEqual(result["state"]["cross_document_status"], "matched")
            self.assertEqual(result["state"]["matched_document_id"], po["document_id"])
            self.assertEqual(result["state"]["agent_history"][-2:], ["cross_document_verification", "routing_agent"])
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


if __name__ == "__main__":
    unittest.main()

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


class CrossDocumentTests(PipelineFixture):

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


if __name__ == "__main__":
    unittest.main()

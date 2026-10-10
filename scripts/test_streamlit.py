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


class StreamlitTests(PipelineFixture):

    def test_streamlit_pages(self):
            from streamlit.testing.v1 import AppTest
            self.process("ui.txt", "receipt", {"seller": "Shop", "issue_date": "2026-10-01", "total": "INR 20.00"})
            with patch("idp.pipeline.agentic_pipeline.AgenticDocumentPipeline", return_value=self.pipeline):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/app.py")).run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.tabs), 4)
                self.assertGreater(len(app.selectbox), 0)


if __name__ == "__main__":
    unittest.main()

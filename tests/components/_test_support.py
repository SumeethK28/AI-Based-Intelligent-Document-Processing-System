from idp.security import INTERNAL
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


class PipelineFixture(unittest.TestCase):

    def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name)
            self.llm = FakeLLM()
            self.baseline = SimpleNamespace(process=self.baseline_result)
            self.pipeline = AgenticDocumentPipeline(self.root / "test.db", baseline=self.baseline, llm=self.llm, _capability=INTERNAL)

    def baseline_result(self, path):
            return SimpleNamespace(extracted_data=None, classification=SimpleNamespace(document_class=SimpleNamespace(value=self.llm.kind)), ocr=SimpleNamespace(full_text="\n".join(self.llm.fields.values()), average_confidence=1))

    def process(self, name, kind, fields):
            self.llm.kind, self.llm.fields = kind, fields
            path = self.root / name
            path.write_text(name)
            return self.pipeline.process(path)

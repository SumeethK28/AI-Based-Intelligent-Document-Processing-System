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

    def setUp(self):
        import streamlit as st
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        super().setUp()

    def test_review_inputs_do_not_leak_between_documents(self):
        from streamlit.testing.v1 import AppTest
        fields = {"seller": "Shop", "issue_date": "2026-10-01", "total": "INR 20.00"}
        first = self.process("first.txt", "receipt", fields)
        second = self.process("second.txt", "receipt", fields)
        with patch("idp.ui.console.get_repository", return_value=self.pipeline.repository), patch.dict("os.environ", {"IDP_DATABASE_PATH": str(self.pipeline.repository.db_path)}), patch("idp.pipeline.agentic_pipeline.AgenticDocumentPipeline", return_value=self.pipeline):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/app.py"), default_timeout=30).run(timeout=30)
            app.radio(key="navigation").set_value("Review Center").run()
            app.selectbox(key="review_document_id").set_value(second["document_id"]).run()
            app.text_area(key=f"review_notes_{second['document_id']}").set_value("Notes for second only").run()
            app.selectbox(key="review_document_id").set_value(first["document_id"]).run()
            self.assertEqual(app.text_area(key=f"review_notes_{first['document_id']}").value, "")
            self.assertEqual(app.selectbox(key=f"review_decision_select_{first['document_id']}").value, "approved")
            self.assertEqual(len(app.exception), 0)

    def test_streamlit_pages(self):
            from streamlit.testing.v1 import AppTest
            self.process("ui.txt", "receipt", {"seller": "Shop", "issue_date": "2026-10-01", "total": "INR 20.00"})
            with patch("idp.ui.console.get_repository", return_value=self.pipeline.repository), patch.dict("os.environ", {"IDP_DATABASE_PATH": str(self.pipeline.repository.db_path)}), patch("idp.pipeline.agentic_pipeline.AgenticDocumentPipeline", return_value=self.pipeline) as factory:
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/app.py"), default_timeout=30).run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.radio(key="navigation").options), 9)
                for page in app.radio(key="navigation").options:
                    app.radio(key="navigation").set_value(page).run()
                    self.assertEqual(len(app.exception), 0, page)
                factory.assert_not_called()
                app.radio(key="navigation").set_value("Overview").run()
                self.assertGreater(len(app.selectbox), 0)

    def test_empty_console_and_overview_navigation(self):
        from streamlit.testing.v1 import AppTest
        with patch("idp.ui.console.get_repository", return_value=self.pipeline.repository), patch.dict("os.environ", {"IDP_DATABASE_PATH": str(self.pipeline.repository.db_path)}):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/app.py"), default_timeout=30).run(timeout=30)
            self.assertEqual(app.metric[0].value, "0")
            next(button for button in app.button if button.label == "Open review cases").click().run()
            self.assertEqual(app.radio(key="navigation").value, "Review Center")
            self.assertEqual(len(app.exception), 0)


if __name__ == "__main__":
    unittest.main()

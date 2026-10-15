"""Component regression tests; API responses are simulated unless explicitly noted."""
import unittest
from pathlib import Path
from unittest.mock import patch



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
            app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "app/app.py"), default_timeout=30).run(timeout=30)
            app.radio(key='navigation').set_value('My Work').run()
            app.radio(key='work_view').set_value('Review Center').run()
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
                app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "app/app.py"), default_timeout=30).run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.radio(key="navigation").options), 5)
                for page in app.radio(key="navigation").options:
                    app.radio(key="navigation").set_value(page).run()
                    self.assertEqual(len(app.exception), 0, page)
                    key = {'Documents':'documents_view','My Work':'work_view','Administration':'administration_view'}.get(page)
                    if key:
                        for view in app.radio(key=key).options:
                            app.radio(key=key).set_value(view).run()
                            self.assertEqual(len(app.exception), 0, view)
                factory.assert_not_called()
                app.radio(key="navigation").set_value("Overview").run()
                self.assertGreater(len(app.selectbox), 0)

    def test_empty_console_and_overview_navigation(self):
        from streamlit.testing.v1 import AppTest
        with patch("idp.ui.console.get_repository", return_value=self.pipeline.repository), patch.dict("os.environ", {"IDP_DATABASE_PATH": str(self.pipeline.repository.db_path)}):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "app/app.py"), default_timeout=30).run(timeout=30)
            self.assertEqual(app.metric[0].value, "0")
            next(button for button in app.button if button.label == "Open review cases").click().run()
            self.assertEqual(app.radio(key="navigation").value, "My Work")
            self.assertEqual(len(app.exception), 0)

    def test_status_and_document_fields_are_plain_wrapping_text(self):
        from streamlit.testing.v1 import AppTest
        result = self.process('status.txt', 'invoice', {'invoice_number':'INV-WRAP',
            'seller':'A long supplier name with multiple business divisions', 'client':'Buyer',
            'issue_date':'2026-10-01','total':'INR 100.00'})
        with patch('idp.ui.console.get_repository',return_value=self.pipeline.repository), patch.dict('os.environ',{'IDP_DATABASE_PATH':str(self.pipeline.repository.db_path)}):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[2]/'app/app.py'),default_timeout=30).run()
            app.radio(key='navigation').set_value('Documents').run()
            self.assertTrue(any(item.value=='Awaiting department review' for item in app.text))
            self.assertTrue(any(item.value=='A long supplier name with multiple business divisions' for item in app.text))
            self.assertTrue(any(item.label=='Field Evidence' for item in app.expander))
            self.assertFalse(app.exception)

    def test_evidence_labels_do_not_render_model_supplied_markdown(self):
        import json
        from streamlit.testing.v1 import AppTest
        result=self.process('evidence.txt','receipt',{'seller':'Shop','issue_date':'2026-10-01','total':'INR 20.00'})
        document=self.pipeline.repository.get_document(result['document_id'])
        state=document['full_result']
        payload='![tracking](https://example.invalid/private)'
        state['field_evidence'][payload]='Shop'
        with self.pipeline.repository.connect() as db:
            db.execute('UPDATE documents SET full_result=? WHERE id=?',(json.dumps(state),document['id']))
        with patch('idp.ui.console.get_repository',return_value=self.pipeline.repository), patch.dict('os.environ',{'IDP_DATABASE_PATH':str(self.pipeline.repository.db_path)}):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[2]/'app/app.py'),default_timeout=30).run()
            app.radio(key='navigation').set_value('Documents').run()
            self.assertTrue(any('example.invalid/private' in item.value for item in app.text))
            self.assertFalse(any('example.invalid/private' in item.value for item in app.markdown))
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()

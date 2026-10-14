"""End-to-end LangGraph → storage → human correction → reprocessing; simulated Groq."""
from idp.security import INTERNAL
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_integration import FakeLLM
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
from idp.review.service import ReviewService, ReviewConflict


class ReviewIntegrationTests(unittest.TestCase):
    def test_pipeline_correction_approval_and_reprocessing_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            llm=FakeLLM()
            def baseline(path):
                return SimpleNamespace(extracted_data=None,classification=SimpleNamespace(document_class=SimpleNamespace(value=llm.kind)),
                    ocr=SimpleNamespace(full_text='\n'.join(llm.fields.values())+'\nINR 110.00',average_confidence=1))
            pipeline=AgenticDocumentPipeline(root/'test.db',baseline=SimpleNamespace(process=baseline),llm=llm, _capability=INTERNAL)
            llm.kind='purchase_order'
            llm.fields={'po_number':'PO-1','order_date':'2026-10-01','vendor':'Supplier','total':'INR 110.00'}
            po=root/'po.txt'
            po.write_text('purchase order')
            pipeline.process(po)
            llm.kind='invoice'
            llm.fields={'invoice_number':'INV-1','issue_date':'2026-10-01','seller':'Supplier','client':'Buyer','total':'INR 130.00','po_reference':'PO-1'}
            source=root/'invoice.txt'
            source.write_text('invoice')
            result=pipeline.process(source)
            self.assertEqual(result['state']['cross_document_status'],'mismatch')
            document=pipeline.repository.get_document(result['document_id'])
            service=ReviewService(pipeline.repository)
            calls=llm.calls
            service.apply_correction(document['id'],document['revision'],{'total':'INR 110.00'},{'total':'INR 110.00'},actor='prototype:alice',reason='OCR-supported total correction')
            corrected=pipeline.repository.get_document(document['id'])
            service.decide(corrected['id'],corrected['revision'],'approved',actor='prototype:alice',reason='Corrected fields reconcile to PO')
            approved=pipeline.repository.get_document(document['id'])
            self.assertEqual(approved['full_result']['cross_document_status'],'matched')
            self.assertEqual(llm.calls,calls)
            with pipeline.repository.connect() as db:
                original=json.loads(db.execute('SELECT original_state FROM processing_versions WHERE id=?',(document['processing_version_id'],)).fetchone()[0])
            self.assertEqual(original['extracted_fields']['total'],'INR 130.00')
            pipeline.process(source,force_reprocess=True)
            after=pipeline.repository.get_document(document['id'])
            self.assertEqual(after['review_decision'],'pending')
            self.assertEqual(after['workflow_status'],'manual_review')
            self.assertNotEqual(after['processing_version_id'],approved['processing_version_id'])
            self.assertEqual([event['event_type'] for event in service.history(document['id'])],['reprocessed','decision','correction'])
            with self.assertRaises(ReviewConflict):
                service.decide(document['id'],approved['revision'],'rejected',actor='prototype:bob',reason='Stale reviewer tab')

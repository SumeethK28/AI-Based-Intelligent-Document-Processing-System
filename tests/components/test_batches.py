"""Actual SQLite, ingestion and LangGraph; all model responses are simulated."""
from idp.security import INTERNAL
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from reportlab.pdfgen import canvas
from PIL import Image

from idp.batch.ingestion import inspect_file, preview, Limits
from idp.batch.service import BatchService, worker_lock, safe_failure
from idp.storage.repository import DocumentRepository
from idp.storage.operations import DocumentFilters, OperationsQueries
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
from _test_support import FakeLLM


def pdf(text='sample', pages=1):
    out = io.BytesIO()
    doc = canvas.Canvas(out)
    for _ in range(pages):
        doc.drawString(60,760,text)
        doc.showPage()
    doc.save()
    return out.getvalue()

PO = {'po_number':'PO-1','order_date':'2026-10-01','vendor':'Supplier','buyer':'Buyer','total':'INR 110.00'}
INVOICE = {'invoice_number':'INV-1','issue_date':'2026-10-02','seller':'Supplier','client':'Buyer','subtotal':'INR 100.00','tax':'INR 10.00','total':'INR 110.00','po_reference':'PO-1'}
RECEIPT = {'receipt_number':'R-1','seller':'Shop','issue_date':'2026-10-01','total':'USD 20.00'}
CONTRACT = {'contract_number':'C-1','contract_title':'Service Agreement','party_a':'Alpha','party_b':'Beta','effective_date':'2026-10-01','expiration_date':'2027-10-01','contract_value':'USD 50.00'}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = DocumentRepository(self.root/'test.db', _capability=INTERNAL)
        self.service = BatchService(self.repo)
        self.llm = FakeLLM()
        self.failure_markers = set()
        def baseline(path):
            with __import__('pymupdf').open(path) as document:
                marker = document[0].get_text().strip()
            if marker in self.failure_markers:
                raise TimeoutError('SECRET should never appear')
            kind, fields = {'po':('purchase_order',PO),'invoice':('invoice',INVOICE),
                            'receipt':('receipt',RECEIPT),'contract':('contract',CONTRACT),
                            'unknown':('invoice',{**INVOICE,'po_reference':'NO-PO'})}[marker]
            self.llm.kind, self.llm.fields = kind, fields
            return SimpleNamespace(extracted_data=None,classification=SimpleNamespace(document_class=SimpleNamespace(value=kind)),
                                   ocr=SimpleNamespace(full_text='\n'.join(fields.values()),average_confidence=1))
        self.pipeline = AgenticDocumentPipeline(self.repo.db_path,baseline=SimpleNamespace(process=baseline),llm=self.llm, _capability=INTERNAL)

    def submit(self,*markers,key='request',force=False):
        return self.service.submit([(marker+'.pdf',pdf(marker)) for marker in markers],request_key=key,force=force)

    def run_job(self,job,**kwargs):
        return self.service.run(lambda:self.pipeline,job,**kwargs)

    def test_mixed_batch_both_po_orders(self):
        for order in [('invoice','po'),('po','invoice')]:
            with self.subTest(order=order):
                if order[0]=='po':
                    self.setUp()  # Independent database for each execution order.
                job = self.submit(*order,'receipt','contract',key=str(order))
                self.run_job(job)
                items = self.service.items(job)
                self.assertFalse(any(item['state']=='failed' for item in items))
                invoice = next(item for item in items if item['filename']=='invoice.pdf')
                state = json.loads(invoice['result_snapshot'])
                self.assertEqual(state['cross_document_status'],'matched')
                self.assertEqual(state['assigned_department'],'Finance')
                self.assertEqual(self.service.summary(job)['unique_documents'],4)

    def test_unmatched_reference_stays_review(self):
        job = self.submit('unknown')
        self.run_job(job)
        self.assertEqual(self.service.items(job)[0]['state'],'review_required')
        self.assertEqual(json.loads(self.service.items(job)[0]['result_snapshot'])['cross_document_status'],'unmatched')

    def test_duplicates_existing_and_same_batch_skip_model(self):
        data = pdf('receipt')
        job = self.service.submit([('one.pdf',data),('two.pdf',data)],request_key='one')
        self.run_job(job)
        self.assertEqual([item['state'] for item in self.service.items(job)],['completed','duplicate'])
        calls = self.llm.calls
        second = self.service.submit([('three.pdf',data)],request_key='two')
        rows,_ = preview([('three.pdf',data)],self.repo)
        self.assertTrue(rows[0]['duplicate'])
        self.run_job(second)
        self.assertEqual(self.llm.calls,calls)
        self.assertEqual(self.service.summary(job)['financial_totals'],[])
        self.assertEqual(len(self.repo.list_documents()),1)

    def test_failure_isolated_and_retry_history(self):
        self.failure_markers.add('receipt')
        job = self.submit('po','receipt','invoice')
        self.run_job(job)
        failed = next(item for item in self.service.items(job) if item['state']=='failed')
        self.assertEqual(sum(item['state']=='completed' for item in self.service.items(job)),2)
        self.assertNotIn('SECRET',failed['safe_error'])
        self.failure_markers.clear()
        self.service.retry(failed['id'])
        self.run_job(job)
        self.assertEqual([row['state'] for row in self.service.attempts(failed['id'])],['failed','completed'])
        with self.assertRaises(ValueError):
            self.service.retry(failed['id'])

    def test_restart_recovers_committed_run_without_side_effect(self):
        job = self.submit('receipt')
        item = self.service.items(job)[0]
        result = self.pipeline.process(self.service.source(item),operation_key=f"batch:{item['id']}:0")
        script = '''import os,sys
from idp.storage.repository import DocumentRepository
from idp.batch.service import worker_lock
from idp.security import INTERNAL
repo=DocumentRepository(sys.argv[1], _capability=INTERNAL)
with worker_lock(repo.db_path):
    with repo.connect() as db:
        db.execute("UPDATE batch_items SET state='processing',attempts=1 WHERE id=?",(int(sys.argv[2]),))
        db.execute("INSERT INTO batch_attempts(item_id,attempt,started_at,state) VALUES(?,1,?,'processing')",(int(sys.argv[2]),repo.timestamp()))
    os._exit(17)
'''
        crashed = subprocess.run([sys.executable,'-c',script,str(self.repo.db_path),str(item['id'])],capture_output=True,timeout=20)
        self.assertEqual(crashed.returncode,17)
        calls = self.llm.calls
        reopened = BatchService(DocumentRepository(self.repo.db_path, _capability=INTERNAL))
        reopened.run(lambda:self.pipeline,job)
        self.assertEqual(reopened.items(job)[0]['run_id'],result['run_id'])
        self.assertEqual(self.llm.calls,calls)
        self.assertEqual(len(self.repo.list_processing_runs()),1)
        self.assertEqual(reopened.attempts(item['id'])[0]['state'],'interrupted')

    def test_bulk_ui_persisted_failure_retry_and_completion(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        self.failure_markers.add('receipt')
        job = self.submit('receipt')
        self.run_job(job)
        with patch('idp.ui.console.get_repository',return_value=self.repo), patch.dict('os.environ',{'IDP_DATABASE_PATH':str(self.repo.db_path)}),patch('idp.ui.console.get_pipeline',return_value=self.pipeline):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[2]/'app/app.py'), default_timeout=30).run(timeout=30)
            app.radio(key='navigation').set_value('Documents').run()
            app.radio(key='documents_view').set_value('Bulk Processing').run()
            self.assertEqual(app.metric[3].value,'1')
            next(button for button in app.button if button.label=='Retry failed item').click().run()
            self.assertEqual(self.service.items(job)[0]['state'],'queued')
            self.failure_markers.clear()
            next(button for button in app.button if button.label=='Start / resume batch').click().run(timeout=30)
            self.assertEqual(self.service.items(job)[0]['state'],'completed')
            self.assertEqual(len(app.exception),0)

    def test_reconciliation_preserves_independent_high_anomaly(self):
        job = self.submit('invoice','po')
        self.run_job(job,max_items=1)
        item = self.service.items(job)[0]
        document = self.repo.get_document(item['document_id'])
        state = document['full_result']
        state['anomalies'].append({'code':'INDEPENDENT_RISK','severity':'high','description':'Unresolved external flag'})
        state['risk_level']='high'
        with self.repo.connect() as db:
            db.execute('UPDATE documents SET full_result=? WHERE id=?',(json.dumps(state),document['id']))
        self.run_job(job)
        after = self.repo.get_document(document['id'])['full_result']
        self.assertEqual(after['cross_document_status'],'matched')
        self.assertEqual(after['risk_level'],'high')
        self.assertNotEqual(after['workflow_status'],'pending_department_review')

    def test_reconciliation_does_not_clear_unexplained_high_risk(self):
        job = self.submit('invoice','po')
        self.run_job(job,max_items=1)
        item = self.service.items(job)[0]
        document = self.repo.get_document(item['document_id'])
        state = document['full_result']
        state['risk_level']='high'
        with self.repo.connect() as db:
            db.execute('UPDATE documents SET full_result=? WHERE id=?',(json.dumps(state),document['id']))
        self.run_job(job)
        after = self.repo.get_document(document['id'])['full_result']
        self.assertEqual(after['cross_document_status'],'matched')
        self.assertEqual(after['risk_level'],'high')
        self.assertNotEqual(after['workflow_status'],'pending_department_review')

    def test_late_duplicate_po_identifier_requires_ambiguity_review(self):
        job = self.submit('po','invoice')
        self.run_job(job,max_items=2)
        # A separate batch adds another byte-distinct PO with the same business ID.
        late = self.service.submit([('second.pdf',pdf('po')),('invoice.pdf',self.service.source(self.service.items(job)[1]).read_bytes())],request_key='late-po')
        self.run_job(late)
        invoice = next(item for item in self.service.items(late) if item['filename']=='invoice.pdf')
        self.assertEqual(json.loads(invoice['result_snapshot'])['cross_document_status'],'ambiguous')
        self.assertEqual(self.repo.get_document(invoice['document_id'])['workflow_status'],'manual_review')

    def test_batch_reconciliation_cannot_overturn_human_escalation(self):
        from idp.review.service import ReviewService
        job=self.submit('invoice','po')
        self.run_job(job,max_items=1)
        item=self.service.items(job)[0]
        document=self.repo.get_document(item['document_id'])
        ReviewService(self.repo).decide(document['id'],document['revision'],'escalated',actor='prototype:reviewer',reason='Check PO source before further processing')
        self.run_job(job)
        after=self.repo.get_document(document['id'])
        self.assertEqual(after['review_decision'],'escalated')
        self.assertEqual(after['workflow_status'],'manual_review')

    def test_policy_pinning_batch_reconciliation_and_analytics(self):
        from idp.policy.service import PolicyService
        from idp.policy.schema import DEFAULT
        from idp.storage.intelligence import IntelligenceQueries
        import copy
        job=self.submit('invoice','po')
        self.run_job(job,max_items=1)
        first=self.service.items(job)[0]
        policy=PolicyService(self.repo)
        config=copy.deepcopy(DEFAULT); config['escalate_all']=True
        version=policy.draft(config,actor='admin',reason='Extra review for new documents')
        preview=policy.preview(version)
        policy.activate(version,preview['id'],actor='admin',reason='Test batch policy boundary',confirmed=True)
        self.run_job(job)
        invoice=self.repo.get_document(first['document_id'])
        self.assertEqual(invoice['full_result']['policy_version_id'],1)
        self.assertEqual(invoice['workflow_status'],'manual_review')  # New PO is restricted by policy.
        self.assertIn('PO_REVIEW_BLOCK',[issue['code'] for issue in invoice['full_result']['cross_document_issues']])
        report=IntelligenceQueries(self.repo).report()
        self.assertEqual(report['batches']['terminal_items'],2)
        self.assertEqual(report['batches']['success_rate'],1)
        self.assertEqual(report['batches']['failure_rate'],0)
        self.assertEqual(report['batches']['attempts'],2)

    def test_analytics_batch_failure_retry_denominators(self):
        from idp.storage.intelligence import IntelligenceQueries
        self.failure_markers.add('receipt')
        job=self.submit('receipt','po')
        self.run_job(job)
        report=IntelligenceQueries(self.repo).report()
        self.assertEqual(report['batches']['failure_rate'],.5)
        failed=next(item for item in self.service.items(job) if item['state']=='failed')
        self.failure_markers.clear()
        self.service.retry(failed['id'])
        self.run_job(job)
        report=IntelligenceQueries(self.repo).report()
        self.assertEqual(report['batches']['failure_rate'],0)
        self.assertEqual(report['batches']['retried_items'],1)
        self.assertEqual(report['batches']['retry_rate'],.5)
        self.assertEqual(report['batches']['failed_attempts'],1)

    def test_repeated_submission_and_concurrent_requests(self):
        files = [('receipt.pdf',pdf('receipt'))]
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _:self.service.submit(files,request_key='same'),range(2)))
        self.assertEqual(ids[0],ids[1])
        self.assertEqual(len(self.service.items(ids[0])),1)
        self.assertEqual(self.service.submit(files,request_key='same'),ids[0])

    def test_worker_lock_prevents_takeover_and_readers_work(self):
        job = self.submit('receipt')
        with worker_lock(self.repo.db_path):
            with self.assertRaises(RuntimeError):
                self.run_job(job)
            self.assertEqual(len(self.service.items(job)),1)

    def test_bounded_execution_does_not_repeat_completed(self):
        job = self.submit('receipt','po')
        self.assertEqual(self.run_job(job,max_items=1),1)
        self.assertEqual(self.service.items(job)[1]['state'],'queued')
        self.assertEqual(self.run_job(job),1)
        calls = self.llm.calls
        self.assertEqual(self.run_job(job),0)
        self.assertEqual(self.llm.calls,calls)

    def test_force_reprocessing_resets_review_once(self):
        data = pdf('receipt')
        first = self.service.submit([('receipt.pdf',data)],request_key='first')
        self.run_job(first)
        document_id = self.service.items(first)[0]['document_id']
        self.repo.update_review(document_id,'approved','Review',expected_revision=self.repo.get_document(document_id)['revision'])
        job = self.service.submit([('receipt.pdf',data)],request_key='forced',force=True)
        self.run_job(job)
        self.assertEqual(self.repo.get_document(document_id)['review_decision'],'pending')
        self.run_job(job)
        self.assertEqual(len(self.repo.list_processing_runs()),2)

    def test_invalid_signatures_sizes_corrupt_pdf_zip_and_limits(self):
        for name,data in [('bad.pdf',b'fake'),('bad.jpg',pdf()),('bad.png',b'fake'),('bad.pdf',b'%PDF-1.7 damaged'),('archive.zip',b'PK')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                inspect_file(name,data)
        with self.assertRaises(ValueError):
            inspect_file('large.pdf',pdf(),Limits(file_bytes=10))
        with self.assertRaises(ValueError):
            inspect_file('pages.pdf',pdf(pages=2),Limits(pages=1))
        out = io.BytesIO()
        Image.new('RGB',(100,100)).save(out,format='PNG')
        with self.assertRaises(ValueError):
            inspect_file('image.png',out.getvalue(),Limits(pixels=50))
        rows,accepted = preview([('one.pdf',pdf()),('two.pdf',pdf())],self.repo,Limits(files=1))
        self.assertEqual(len(accepted),1)
        self.assertFalse(rows[1]['accepted'])

    def test_changed_source_fails_without_ai(self):
        job = self.submit('receipt')
        item = self.service.items(job)[0]
        self.service.source(item).write_bytes(pdf('po'))
        self.run_job(job)
        self.assertEqual(self.service.items(job)[0]['state'],'failed')
        self.assertEqual(self.llm.calls,0)

    def test_currency_amount_batch_filters_and_indexed_search(self):
        job = self.submit('po','invoice','receipt','contract')
        self.run_job(job)
        queries = OperationsQueries(self.repo)
        self.assertEqual(queries.page(DocumentFilters(search='INV-1',currency='INR',min_amount=100,max_amount=120,batch_id=job))[1],1)
        self.assertEqual(queries.page(DocumentFilters(search='C-1'))[1],1)
        self.assertEqual(queries.page(DocumentFilters(search='R-1'))[1],1)
        self.assertEqual(queries.page(DocumentFilters(currency='EUR'))[1],0)
        self.assertEqual(len(queries.export(DocumentFilters(batch_id=job))),4)
        with self.repo.connect() as db:
            plan = str([tuple(row) for row in db.execute("EXPLAIN QUERY PLAN SELECT document_id FROM document_search WHERE currency='INR' AND amount>10")])
        self.assertIn('search_money',plan)

    def test_export_sanitization_and_unique_financial_totals(self):
        data = pdf('invoice')
        job = self.service.submit([('=formula.pdf',data),('copy.pdf',data),('po.pdf',pdf('po'))],request_key='finance')
        self.run_job(job)
        summary = self.service.summary(job)
        self.assertEqual(summary['unique_documents'],2)
        self.assertEqual(summary['financial_totals'][0]['amount'],'110.00')
        self.assertIn("'=formula.pdf",self.service.csv(summary['items']))
        self.assertEqual(summary['items'][0]['filename'],'=formula.pdf')

    def test_rate_limit_safe_message_and_retry_bound(self):
        error = RuntimeError('secret')
        error.status_code = 429
        self.assertEqual(safe_failure(error)[0],'rate_limit')
        job = self.submit('receipt')
        with patch.object(self.pipeline,'process',side_effect=error):
            for attempt in range(5):
                self.run_job(job)
                item = self.service.items(job)[0]
                self.assertEqual(item['error_category'],'rate_limit')
                if attempt < 4:
                    self.service.retry(item['id'])
            with self.assertRaises(ValueError):
                self.service.retry(item['id'])

    def test_additive_migration_backup_preserves_original_records(self):
        legacy = self.root/'legacy.db'
        with closing(sqlite3.connect(legacy)) as db:
            db.executescript('''CREATE TABLE documents(id INTEGER PRIMARY KEY,filename TEXT,file_hash TEXT,document_type TEXT,
                extracted_data TEXT,full_result TEXT,workflow_status TEXT,assigned_department TEXT,review_decision TEXT,review_notes TEXT,created_at TEXT,updated_at TEXT);
                CREATE TABLE processing_runs(id INTEGER PRIMARY KEY,document_id INTEGER,filename TEXT,is_duplicate INTEGER,processed_at TEXT);''')
            db.execute("INSERT INTO documents VALUES(1,'original','hash','receipt','{}','{}','manual_review','Review','approved','Keep','date','date')")
            db.execute("INSERT INTO processing_runs VALUES(1,1,'original',0,'date')")
            before = tuple(db.execute('SELECT * FROM documents').fetchone())
            db.commit()
        repository = DocumentRepository(legacy, _capability=INTERNAL)
        with repository.connect() as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM documents').fetchone())[:len(before)],before)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(len(list(self.root.glob('legacy.db.before_batch_v1.*.db'))),1)
        DocumentRepository(legacy, _capability=INTERNAL)
        self.assertEqual(len(list(self.root.glob('legacy.db.before_batch_v1.*.db'))),1)


if __name__ == '__main__':
    unittest.main()

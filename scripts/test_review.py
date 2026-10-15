"""Real SQLite/deterministic agents; no live provider calls or production writes."""
from idp.security import INTERNAL
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from idp.review.service import ReviewService, ReviewConflict, UnsafeApproval
from idp.storage.repository import DocumentRepository
from idp.agents.validation_agent import ValidationAgent
from idp.agents.anomaly_agent import AnomalyDetectionAgent
from idp.agents.cross_document_agent import CrossDocumentAgent
from idp.agents.routing_agent import WorkflowRoutingAgent


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.repo=DocumentRepository(self.root/'review.db', _capability=INTERNAL)
        self.service=ReviewService(self.repo)
        self.counter=0

    def create(self,kind='receipt',fields=None,extra='',**metadata):
        self.counter+=1
        fields=fields or {'seller':'Shop','issue_date':'2026-10-01','total':'USD 20.00'}
        state={'document_type':kind,'extracted_fields':fields,'ocr_text':'\n'.join(fields.values())+'\n'+extra,
               'field_evidence':dict(fields),'agent_history':[],**metadata}
        state.update(ValidationAgent().run(state))
        state.update(AnomalyDetectionAgent().run(state))
        state.update(CrossDocumentAgent(self.repo).run(state))
        state.update(WorkflowRoutingAgent().run(state))
        path=self.root/f'document{self.counter}.txt'
        path.write_text(str(self.counter))
        return self.repo.save_processed_document(path,path.name,state)['document_id']

    def revision(self,id):
        return self.repo.get_document(id)['revision']

    def decide(self,id,decision='approved',**kwargs):
        return self.service.decide(id,self.revision(id),decision,actor='prototype:alice',reason='Verified fixture source',**kwargs)

    def test_valid_correction_preserves_original_and_has_provenance(self):
        id=self.create(extra='USD 25.00')
        before=self.repo.get_document(id)
        with patch('idp.llm.provider.GroqProvider.generate_structured',side_effect=AssertionError('No provider call allowed')) as llm:
            preview=self.service.preview_correction(id,{'total':'USD 25.00'},{'total':'USD 25.00'})
            self.assertTrue(preview['state']['validation_passed'])
            self.service.apply_correction(id,before['revision'],{'total':'USD 25.00'},{'total':'USD 25.00'},actor='prototype:alice',reason='OCR supports corrected total')
            self.decide(id)
            llm.assert_not_called()
        current=self.repo.get_document(id)
        self.assertEqual(current['extracted_data']['total'],'USD 25.00')
        self.assertEqual(current['full_result']['ocr_text'],before['full_result']['ocr_text'])
        self.assertEqual(current['full_result']['field_provenance']['total']['source'],'human_correction')
        with self.repo.connect() as db:
            original=json.loads(db.execute('SELECT original_state FROM processing_versions WHERE id=?',(before['processing_version_id'],)).fetchone()[0])
        self.assertEqual(original['extracted_fields']['total'],'USD 20.00')
        self.assertEqual([event['event_type'] for event in self.service.history(id)],['decision','correction'])

    def test_invalid_correction_is_retained_but_cannot_be_approved(self):
        id=self.create()
        self.service.apply_correction(id,self.revision(id),{'total':'USD 999.00'},{'total':'USD 999.00'},actor='prototype:alice',reason='Draft investigation')
        self.assertFalse(self.repo.get_document(id)['full_result']['validation_passed'])
        with self.assertRaises(UnsafeApproval):
            self.decide(id)
        self.assertEqual(len(self.service.history(id)),1)
        self.assertEqual(self.repo.get_document(id)['workflow_status'],'manual_review')

    def test_mandatory_blank_and_unrelated_quote_block_approval(self):
        id=self.create(extra='USD 25.00')
        self.service.apply_correction(id,self.revision(id),{'total':'USD 25.00'},{'total':'Shop'},actor='alice',reason='Draft quote')
        with self.assertRaises(UnsafeApproval):
            self.decide(id)
        self.service.apply_correction(id,self.revision(id),{'seller':None},{'seller':''},actor='alice',reason='Seller unreadable')
        with self.assertRaises(UnsafeApproval):
            self.decide(id)

    def test_po_mismatch_persists_and_reference_cannot_be_removed(self):
        self.create('purchase_order',{'po_number':'PO-1','order_date':'2026-10-01','vendor':'Acme','total':'INR 110.00'})
        id=self.create('invoice',{'invoice_number':'INV-1','issue_date':'2026-10-01','seller':'Acme','client':'Buyer','total':'INR 120.00','po_reference':'PO-1'})
        with self.assertRaises(UnsafeApproval):
            self.decide(id)
        self.service.apply_correction(id,self.revision(id),{'po_reference':None},{'po_reference':''},actor='alice',reason='Investigate reference')
        with self.assertRaises(UnsafeApproval):
            self.decide(id)
        self.assertIn('po_reference',self.repo.get_document(id)['full_result']['human_evidence_errors'])
        self.decide(id,'escalated')
        self.assertEqual(self.service.case(id)['case_status'],'escalated')

    def test_revalidation_resolves_real_po_total_correction(self):
        self.create('purchase_order',{'po_number':'PO-1','order_date':'2026-10-01','vendor':'Acme','total':'INR 110.00'})
        id=self.create('invoice',{'invoice_number':'INV-1','issue_date':'2026-10-01','seller':'Acme','client':'Buyer','total':'INR 120.00','po_reference':'PO-1'},extra='INR 110.00')
        self.service.apply_correction(id,self.revision(id),{'total':'INR 110.00'},{'total':'INR 110.00'},actor='alice',reason='Original OCR has correct total')
        self.assertEqual(self.repo.get_document(id)['full_result']['cross_document_status'],'matched')
        self.decide(id)

    def test_high_risk_and_unsupported_contract_cannot_be_approved(self):
        id=self.create(fields={'seller':'Shop','issue_date':'2026-10-01','total':'USD 200000.00'})
        with self.assertRaises(UnsafeApproval):
            self.decide(id)
        contract=self.create('contract',{'contract_title':'Service Agreement','party_a':'Alpha','party_b':'Beta','effective_date':'2026-10-01'},
                             contract_parties=['Alpha','Beta'],unsupported_contract_reasons=['Third party not represented'])
        with self.assertRaises(UnsafeApproval):
            self.decide(contract)
        self.decide(contract,'needs_correction')

    def test_decisions_require_identity_reason_and_revision(self):
        id=self.create()
        for actor,reason,revision in [('','Reason',self.revision(id)),('alice','',self.revision(id)),('alice','Reason',None)]:
            with self.assertRaises(ValueError):
                self.service.decide(id,revision,'approved',actor=actor,reason=reason)
        with self.assertRaises(ValueError):
            self.repo.update_review(id,'approved','Valid reason')
        self.assertEqual(self.service.history(id),[])
        with self.assertRaises(ValueError):
            self.service.decide(id,self.revision(id),'approved',actor='system:impersonated',reason='Not an authenticated system actor')

    def test_rejected_requested_correction_and_escalation_are_traceable(self):
        for decision in ('rejected','needs_correction','escalated'):
            id=self.create()
            self.decide(id,decision)
            event=self.service.history(id)[0]
            self.assertEqual(event['decision'],decision)
            self.assertTrue(event['reason'])
            self.assertNotEqual(self.repo.get_document(id)['workflow_status'],'pending_department_review')
            self.assertEqual(self.repo.get_document(id)['full_result']['ocr_text'],json.loads(self.raw_version(id))['ocr_text'])

    def raw_version(self,id):
        with self.repo.connect() as db:
            return db.execute('SELECT original_state FROM processing_versions WHERE document_id=? ORDER BY id LIMIT 1',(id,)).fetchone()[0]

    def test_concurrent_decisions_allow_only_one_revision(self):
        id=self.create()
        revision=self.revision(id)
        def decide(actor):
            try:
                self.service.decide(id,revision,'rejected',actor=actor,reason='Concurrent fixture')
                return 'saved'
            except ReviewConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(decide,['alice','bob']))
        self.assertEqual(sorted(outcomes),['conflict','saved'])
        self.assertEqual(len(self.service.history(id)),1)

    def test_immutable_events_and_versions(self):
        id=self.create()
        self.decide(id)
        for table in ('review_events','processing_versions'):
            for sql in (f'DELETE FROM {table}',f"UPDATE {table} SET document_id=document_id"):
                with self.assertRaises(sqlite3.IntegrityError), self.repo.connect() as db:
                    db.execute(sql)
        self.assertEqual(len(self.service.history(id)),1)

    def test_claim_reassignment_status_and_priority_have_events(self):
        id=self.create()
        self.service.manage(id,self.revision(id),'claim',actor='alice',reason='Working this case')
        with self.assertRaises(ReviewConflict):
            self.service.manage(id,self.revision(id),'claim',actor='bob',reason='Attempt claim')
        self.service.manage(id,self.revision(id),'assign',actor='alice',reason='Legal help',team='Legal',assignee='bob')
        self.service.manage(id,self.revision(id),'status',actor='bob',reason='Wait for source',status='on_hold')
        self.service.manage(id,self.revision(id),'priority',actor='bob',reason='Deadline',priority='urgent')
        self.assertEqual(self.service.case(id)['assignee'],'bob')
        self.assertEqual(self.service.case(id)['team'],'Legal')
        self.assertEqual(self.repo.get_document(id)['assigned_department'],'Expense Processing')
        self.assertEqual(len(self.service.history(id)),4)
        self.assertEqual(self.service.history(id)[0]['new_values']['updated_at'],self.service.case(id)['updated_at'])
        self.decide(id)
        with self.assertRaises(ValueError):
            self.service.manage(id,self.revision(id),'claim',actor='bob',reason='Claim must not reopen approval')
        with self.assertRaises(ValueError):
            self.service.manage(id,self.revision(id),'status',actor='bob',reason='Bypass decision',status='open')

    def test_department_queues_show_po_exceptions_and_real_age(self):
        invoice=self.create('invoice',{'invoice_number':'I-1','issue_date':'2026-10-01','seller':'Acme','client':'Buyer','total':'INR 20.00','po_reference':'NO-PO'})
        for team in ('Finance','Procurement'):
            rows,total=self.service.queue(team=team)
            self.assertEqual(total,1)
            self.assertEqual(rows[0]['id'],invoice)
            self.assertGreaterEqual(rows[0]['age_days'],0)

    def test_reprocessing_keeps_previous_corrections_and_reopens_case(self):
        id=self.create(extra='USD 25.00')
        self.service.apply_correction(id,self.revision(id),{'total':'USD 25.00'},{'total':'USD 25.00'},actor='alice',reason='OCR correction')
        self.decide(id)
        old_revision=self.revision(id)
        state=json.loads(self.raw_version(id))
        self.repo.save_reprocessed_document(self.root/'document1.txt','document1.txt',state)
        self.assertEqual(self.repo.get_document(id)['review_decision'],'pending')
        self.assertEqual(self.service.case(id)['case_status'],'open')
        self.assertEqual([event['event_type'] for event in self.service.history(id)],['reprocessed','decision','correction'])
        self.assertEqual(json.loads(self.raw_version(id))['extracted_fields']['total'],'USD 20.00')
        with self.assertRaises(ReviewConflict):
            self.service.decide(id,old_revision,'approved',actor='alice',reason='Stale processing version')

    def test_stale_correction_and_unknown_fields_are_rejected(self):
        id=self.create(extra='USD 25.00')
        revision=self.revision(id)
        self.service.manage(id,revision,'claim',actor='alice',reason='Working')
        with self.assertRaises(ReviewConflict):
            self.service.apply_correction(id,revision,{'total':'USD 25.00'},{'total':'USD 25.00'},actor='bob',reason='Stale preview')
        with self.assertRaises(ValueError):
            self.service.preview_correction(id,{'ocr_text':'Fabricated'}, {})

    def test_empty_optional_editor_fields_are_not_fabricated_corrections(self):
        id=self.create(extra='USD 25.00')
        preview=self.service.preview_correction(id,{'total':'USD 25.00','tax':None,'subtotal':None},{'total':'USD 25.00','tax':'','subtotal':''})
        self.assertEqual(preview['changed_fields'],['total'])

    def test_rejected_po_invalidates_previous_invoice_approval(self):
        po=self.create('purchase_order',{'po_number':'PO-1','order_date':'2026-10-01','vendor':'Acme','total':'INR 110.00'})
        invoice=self.create('invoice',{'invoice_number':'I-1','issue_date':'2026-10-01','seller':'Acme','client':'Buyer','total':'INR 110.00','po_reference':'PO-1'})
        self.decide(invoice)
        self.decide(po,'rejected')
        self.assertEqual(self.repo.get_document(invoice)['review_decision'],'needs_correction')
        self.assertEqual(self.repo.get_document(invoice)['workflow_status'],'manual_review')
        self.assertEqual(self.service.history(invoice)[0]['event_type'],'po_dependency_change')
        with self.assertRaises(UnsafeApproval):
            self.decide(invoice)

    def test_missing_retained_original_and_reload_history(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        id=self.create()
        self.service.manage(id,self.revision(id),'claim',actor='alice',reason='Inspection')
        with patch('idp.ui.console.get_repository',return_value=self.repo), patch.dict('os.environ',{'IDP_DATABASE_PATH':str(self.repo.db_path)}):
            for _ in range(2):
                app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app/app.py'), default_timeout=30).run(timeout=30)
                app.radio(key='navigation').set_value('My Work').run(timeout=30)
                app.radio(key='work_view').set_value('Review Center').run(timeout=30)
                self.assertEqual(len(app.exception),0)
                self.assertTrue(any('No retained batch source' in item.value for item in app.caption))
                self.assertEqual(app.selectbox(key='review_document_id').value,id)
        self.assertEqual(self.service.history(id)[0]['actor'],'alice')


if __name__=='__main__':
    unittest.main()

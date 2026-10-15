"""Versioned policy regression tests. Provider responses are simulated."""
from idp.security import INTERNAL
import copy
import sqlite3
from contextlib import closing
from datetime import date

from _test_support import PipelineFixture
from idp.policy.schema import DEFAULT, validate_config
from idp.policy.service import PolicyService
from idp.review.service import ReviewService, ReviewConflict, UnsafeApproval
from idp.storage.intelligence import IntelligenceQueries
from idp.storage.operations import DocumentFilters
from idp.storage.repository import DocumentRepository


class PolicyTests(PipelineFixture):
    def setUp(self):
        super().setUp()
        self.repo=self.pipeline.repository
        self.policy=PolicyService(self.repo)

    def invoice(self,name='invoice.txt',number='INV-1',total='INR 100.00',**extra):
        return self.process(name,'invoice',{'invoice_number':number,'issue_date':'2026-10-01','seller':'Supplier','client':'Buyer','total':total,**extra})

    def activate(self,**changes):
        config=copy.deepcopy(DEFAULT); config.update(changes)
        version=self.policy.draft(config,actor='prototype:admin',reason='Controlled test policy')
        preview=self.policy.preview(version)
        self.policy.activate(version,preview['id'],actor='prototype:admin',reason='Test activation',confirmed=True)
        return version

    def test_activation_preview_pinning_and_rollback(self):
        first=self.invoice()
        version=self.activate(require_po_reference=True)
        self.assertEqual(self.repo.get_document(first['document_id'])['full_result']['policy_version_id'],1)
        second=self.invoice('second.txt','INV-2')
        self.assertEqual(second['state']['policy_version_id'],version)
        self.assertIn('po_reference',second['state']['policy_failed_rules'])
        self.assertEqual(second['state']['workflow_status'],'manual_review')
        preview=self.policy.preview(1)
        self.policy.activate(1,preview['id'],actor='prototype:admin',reason='Rollback after preview',confirmed=True)
        self.assertEqual(self.policy.active()['id'],1)
        self.assertEqual(len(self.policy.history()),3)
        self.assertEqual(self.repo.get_document(second['document_id'])['full_result']['policy_version_id'],version)

    def test_invalid_conflicting_and_unsafe_configuration(self):
        for changes in ({'po_tolerance':'1.01'},{'arithmetic_tolerance':'.03'},{'duplicate_identifiers':'ignore'},
            {'unknown_currency_threshold':'NaN'},{'require_po_reference':'false'},{'high_value_thresholds':{'usd':'10'}},
            {'departments':{'invoice':'Finance'}},{'disable_evidence':True}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_config({**copy.deepcopy(DEFAULT),**changes})
        config=copy.deepcopy(DEFAULT); config['mandatory_fields']['invoice'].remove('seller')
        with self.assertRaises(ValueError): validate_config(config)

    def test_currency_specific_threshold_edges(self):
        self.invoice()
        self.activate(high_value_thresholds={'INR':'100','USD':'1000'})
        at=self.invoice('at.txt','INV-2','INR 100.00')
        above=self.invoice('above.txt','INV-3','INR 100.01')
        usd=self.invoice('usd.txt','INV-4','USD 100.01')
        self.assertEqual(at['state']['workflow_status'],'pending_department_review')
        self.assertEqual(above['state']['workflow_status'],'manual_review')
        self.assertEqual(usd['state']['workflow_status'],'pending_department_review')

    def test_po_tolerance_edges_and_supplier_currency_guards(self):
        self.process('po.txt','purchase_order',{'po_number':'PO-1','order_date':'2026-10-01','vendor':'Supplier','total':'INR 100.00'})
        self.activate(po_tolerance='0.50')
        equal=self.invoice('equal.txt','INV-1','INR 100.50',po_reference='PO-1')
        over=self.invoice('over.txt','INV-2','INR 100.51',po_reference='PO-1')
        wrong=self.invoice('currency.txt','INV-3','USD 100.00',po_reference='PO-1')
        vendor=self.invoice('vendor.txt','INV-4','INR 100.00',po_reference='PO-1',seller='Other Supplier')
        self.assertEqual(equal['state']['cross_document_status'],'matched')
        self.assertEqual(over['state']['cross_document_status'],'mismatch')
        self.assertEqual(wrong['state']['cross_document_status'],'mismatch')
        self.assertEqual(vendor['state']['workflow_status'],'manual_review')

    def test_rule_attribution_and_duplicate_identifiers(self):
        self.invoice()
        duplicate=self.invoice('distinct-source.txt')
        self.assertFalse(duplicate['duplicate'])
        self.assertIn('duplicate_identifier',duplicate['state']['policy_failed_rules'])
        self.assertTrue(all(rule['policy_version_id']==1 for rule in duplicate['state']['rule_outcomes']))
        exact=self.pipeline.process(self.root/'invoice.txt')
        self.assertTrue(exact['duplicate'])
        self.assertEqual(exact['state']['policy_version_id'],1)

    def test_stale_preview_confirmation_and_subset(self):
        first=self.invoice()
        draft=self.policy.draft(DEFAULT,actor='admin',reason='Test')
        preview=self.policy.preview(draft)
        with self.assertRaises(ValueError): self.policy.activate(draft,preview['id'],actor='admin',reason='Test')
        subset=self.policy.preview(draft,[first['document_id']])
        with self.assertRaises(ReviewConflict): self.policy.activate(draft,subset['id'],actor='admin',reason='Test',confirmed=True)
        document=self.repo.get_document(first['document_id'])
        ReviewService(self.repo).manage(document['id'],document['revision'],'priority',actor='reviewer',reason='Urgency',priority='high')
        with self.assertRaises(ReviewConflict): self.policy.activate(draft,preview['id'],actor='admin',reason='Test',confirmed=True)

    def test_explicit_reevaluation_restrictions_history_and_stale_revision(self):
        first=self.invoice(); document=self.repo.get_document(first['document_id'])
        review=ReviewService(self.repo)
        review.decide(document['id'],document['revision'],'rejected',actor='reviewer',reason='Reject source')
        version=self.activate(require_po_reference=True)
        before=self.repo.get_document(document['id'])
        with self.assertRaises(ValueError): self.policy.reevaluate(before['id'],before['revision'],version,actor='admin',reason='Recheck')
        self.policy.reevaluate(before['id'],before['revision'],version,actor='admin',reason='Recheck',confirmed=True)
        after=self.repo.get_document(before['id'])
        self.assertEqual(after['review_decision'],'rejected')
        self.assertEqual(after['workflow_status'],'rejected')
        self.assertEqual(after['processing_version_id'],before['processing_version_id'])
        self.assertEqual(review.history(before['id'])[0]['rule_versions']['policy_version_id'],version)
        with self.assertRaises(ReviewConflict): self.policy.reevaluate(before['id'],before['revision'],version,actor='admin',reason='Stale',confirmed=True)
        with self.assertRaises(UnsafeApproval): review.decide(after['id'],after['revision'],'approved',actor='reviewer',reason='Cannot bypass missing PO')

    def test_policy_reevaluation_resets_approval_and_po_dependency(self):
        po=self.process('po.txt','purchase_order',{'po_number':'PO-1','order_date':'2026-10-01','vendor':'Supplier','total':'INR 100.00'})
        invoice=self.invoice(po_reference='PO-1')
        review=ReviewService(self.repo); document=self.repo.get_document(invoice['document_id'])
        review.decide(document['id'],document['revision'],'approved',actor='reviewer',reason='Matched')
        version=self.activate()
        document=self.repo.get_document(po['document_id'])
        self.policy.reevaluate(document['id'],document['revision'],version,actor='admin',reason='New policy',confirmed=True)
        self.assertEqual(self.repo.get_document(invoice['document_id'])['review_decision'],'needs_correction')
        self.assertEqual(self.repo.get_document(invoice['document_id'])['workflow_status'],'manual_review')

    def test_failure_conservatively_blocks_routing(self):
        first=self.invoice(); state=first['state']
        state['policy_version_id']=999999
        checked=ReviewService(self.repo).validate(state)
        self.assertEqual(checked['workflow_status'],'manual_review')
        self.assertIn('policy_engine_failure',checked['policy_failed_rules'])

    def test_immutable_versions_previews_and_activations(self):
        self.invoice(); version=self.activate()
        with self.repo.connect() as db:
            for table in ('policy_versions','policy_previews','policy_activations'):
                with self.subTest(table=table),self.assertRaises(sqlite3.IntegrityError):
                    db.execute('DELETE FROM '+table)
        self.assertEqual(self.policy.active()['id'],version)

    def test_additive_existing_database_migration(self):
        self.invoice()
        copy_path=self.root/'legacy.db'
        with self.repo.connect() as source:
            with closing(sqlite3.connect(copy_path)) as destination: source.backup(destination)
        with closing(sqlite3.connect(copy_path)) as db:
            before=db.execute('SELECT * FROM documents').fetchall()
            originals=db.execute('SELECT * FROM processing_versions').fetchall()
            for table in ('policy_activations','policy_previews','policy_active','policy_versions'):
                db.execute('DROP TABLE '+table)
            db.commit()
        migrated=DocumentRepository(copy_path, _capability=INTERNAL)
        with migrated.connect() as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM documents')],before)
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM processing_versions')],originals)
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual(len(list(self.root.glob('legacy.db.before_policy_v1.*.db'))),1)

    def test_analytics_currency_totals_duplicate_denominators_and_filters(self):
        first=self.invoice('one.txt','INV-1','INR 100.00'); self.invoice('two.txt','INV-2','USD 200.00')
        self.pipeline.process(self.root/'one.txt')
        report=IntelligenceQueries(self.repo).report()
        self.assertEqual(report['unique_documents'],2)
        self.assertEqual(report['recorded_submissions'],3)
        self.assertEqual(report['duplicate_submissions'],1)
        self.assertEqual(report['duplicate_submission_rate'],1/3)
        self.assertEqual({row['currency']:row['extracted_value'] for row in report['financial']['currency']},{'INR':'100.00','USD':'200.00'})
        self.assertEqual(report['processing_time']['samples'],2)
        self.assertEqual(IntelligenceQueries(self.repo).report(DocumentFilters(currency='USD'))['unique_documents'],1)
        self.assertEqual(IntelligenceQueries(self.repo).report(DocumentFilters(start_date=date(2030,1,1)))['unique_documents'],0)
        document=self.repo.get_document(first['document_id'])
        ReviewService(self.repo).manage(document['id'],document['revision'],'claim',actor='reviewer',reason='Start')
        self.assertEqual(IntelligenceQueries(self.repo).report()['intervened_documents'],1)

    def test_configured_fields_contract_dates_arithmetic_and_routing(self):
        self.invoice()
        config=copy.deepcopy(DEFAULT)
        config['mandatory_fields']['receipt'].append('payment_method')
        config['require_contract_expiration']=True
        config['departments']['receipt']='Finance'
        config['arithmetic_tolerance']='0'
        self.activate(**config)
        receipt=self.process('receipt.txt','receipt',{'seller':'Shop','issue_date':'2026-10-01','total':'INR 10.00'})
        self.assertFalse(receipt['state']['validation_passed'])
        receipt=self.process('complete.txt','receipt',{'seller':'Shop','issue_date':'2026-10-01','total':'INR 10.00','payment_method':'Cash'})
        self.assertEqual(receipt['state']['assigned_department'],'Finance')
        contract=self.process('contract.txt','contract',{'contract_title':'Agreement','party_a':'A Corp','party_b':'B Corp','effective_date':'2026-10-01'})
        self.assertIn('contract_expiration',contract['state']['policy_failed_rules'])
        wrong=self.process('arithmetic.txt','receipt',{'seller':'Shop','issue_date':'2026-10-01','total':'INR 10.01','subtotal':'INR 9.00','tax':'INR 1.00','payment_method':'Cash'})
        self.assertIn('arithmetic',wrong['state']['policy_failed_rules'])


if __name__=='__main__':
    import unittest
    unittest.main()

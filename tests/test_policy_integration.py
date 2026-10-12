"""Actual LangGraph/SQLite/review integration; simulated provider only."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_integration import FakeLLM
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
from idp.policy.schema import DEFAULT
from idp.policy.service import PolicyService
from idp.review.service import ReviewService, UnsafeApproval


class PolicyIntegrationTests(unittest.TestCase):
    def test_policy_activation_reprocessing_and_guarded_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); llm=FakeLLM()
            baseline=SimpleNamespace(process=lambda path:SimpleNamespace(extracted_data=None,
                classification=SimpleNamespace(document_class=SimpleNamespace(value=llm.kind)),
                ocr=SimpleNamespace(full_text='\n'.join(llm.fields.values()),average_confidence=1)))
            pipeline=AgenticDocumentPipeline(root/'test.db',baseline=baseline,llm=llm)
            llm.kind='invoice'; llm.fields={'invoice_number':'INV-1','issue_date':'2026-10-01','seller':'Supplier','client':'Buyer','total':'INR 100.00'}
            source=root/'invoice.txt'; source.write_text('synthetic invoice source')
            first=pipeline.process(source)
            policy=PolicyService(pipeline.repository); config=copy.deepcopy(DEFAULT); config['require_po_reference']=True
            version=policy.draft(config,actor='prototype:admin',reason='Require PO references')
            preview=policy.preview(version)
            policy.activate(version,preview['id'],actor='prototype:admin',reason='Activate after preview',confirmed=True)
            calls=llm.calls
            duplicate=pipeline.process(source)
            self.assertEqual(llm.calls,calls)
            self.assertEqual(duplicate['state']['policy_version_id'],1)
            reprocessed=pipeline.process(source,force_reprocess=True)
            self.assertEqual(reprocessed['state']['policy_version_id'],version)
            self.assertEqual(reprocessed['state']['workflow_status'],'manual_review')
            document=pipeline.repository.get_document(first['document_id'])
            with self.assertRaises(UnsafeApproval):
                ReviewService(pipeline.repository).decide(document['id'],document['revision'],'approved',actor='prototype:reviewer',reason='No bypass')
            with pipeline.repository.connect() as db:
                originals=db.execute('SELECT original_state FROM processing_versions ORDER BY id').fetchall()
            import json
            self.assertEqual([json.loads(row[0])['policy_version_id'] for row in originals],[1,version])
            self.assertTrue(all(rule['policy_version_id']==version for rule in reprocessed['state']['rule_outcomes']))

    def test_graph_policy_failure_blocks_with_preserved_extraction(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); llm=FakeLLM(); llm.kind='receipt'
            llm.fields={'seller':'Shop','issue_date':'2026-10-01','total':'INR 20.00'}
            baseline=SimpleNamespace(process=lambda path:SimpleNamespace(extracted_data=None,
                classification=SimpleNamespace(document_class=SimpleNamespace(value='receipt')),
                ocr=SimpleNamespace(full_text='\n'.join(llm.fields.values()),average_confidence=1)))
            pipeline=AgenticDocumentPipeline(root/'test.db',baseline=baseline,llm=llm)
            source=root/'receipt.txt'; source.write_text('synthetic receipt')
            with patch.object(PolicyService,'active',side_effect=RuntimeError('Simulated storage fault')):
                result=pipeline.process(source)
            self.assertEqual(result['state']['extracted_fields']['total'],'INR 20.00')
            self.assertEqual(result['state']['workflow_status'],'manual_review')
            self.assertIn('policy_engine_failure',result['state']['policy_failed_rules'])

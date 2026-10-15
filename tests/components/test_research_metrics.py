"""Metric bookkeeping tests; these are not model evaluations."""
import unittest
import hashlib
import json
import tempfile
from pathlib import Path
from research_metrics import analyse,equivalent,score_fields,wilson
from research_ablation import parsed_fields,RecordedProvider,prepare_manifest
from idp.llm.schemas import AIClassificationResult,AIExtractionResult
from analyze_human_study import grade


class ResearchMetricTests(unittest.TestCase):
    def test_wrong_value_is_false_positive_and_false_negative(self):
        rows,counts=score_fields({'seller':'Seller A','total':'INR 12.00'},
                                {'seller':'Buyer B','total':'INR 12.00','tax_id':'unknown'},'invoice')
        self.assertEqual((counts['tp'],counts['fp'],counts['fn']),(1,1,1))
        self.assertEqual(counts['unannotated_predictions'],{'tax_id':'unknown'})

    def test_abstention_and_currency_are_not_correct(self):
        _,counts=score_fields({'total':'INR 12.00'},{},'receipt')
        self.assertEqual((counts['tp'],counts['fp'],counts['fn']),(0,0,1))
        self.assertFalse(equivalent('total','USD 12.00','INR 12.00'))
        self.assertFalse(equivalent('total',None,'INR 12.00'))

    def test_small_sample_interval_is_not_certain(self):
        interval=wilson(5,5)
        self.assertLess(interval[0],.6)
        self.assertAlmostEqual(interval[1],1)
        self.assertIsNone(wilson(0,0))

    def test_failed_cases_are_preserved_and_excluded_from_completed_accuracy(self):
        report={'documents':[{'filename':'failure','completed':False,'error_type':'TimeoutError'},
            {'filename':'receipt','completed':True,'expected_classification':'receipt',
             'expected':{'seller':'Shop'},'state':{'document_type':'receipt','extracted_fields':{'seller':'Shop'}}}]}
        metrics,rows=analyse(report)
        self.assertEqual((metrics['attempted'],metrics['completed'],metrics['classification_correct']),(2,1,1))
        self.assertEqual(len(rows),1)

    def test_raw_ablation_excludes_metadata_without_repairing_fields(self):
        fields=parsed_fields({'seller':None,'total':'12.00','confidence':.9,
                              'field_evidence':{'total':'INR 12.00'},'contract_parties':[]})
        self.assertEqual(fields,{'total':'12.00'})

    def test_recorded_provider_preserves_role_values_instead_of_ground_truth(self):
        # Synthetic unit fixture, not a live-model test.
        replay=RecordedProvider({'document_type':'invoice','confidence':.8},
                                {'seller':'Wrong role value','confidence':.8})
        self.assertEqual(replay.generate_structured(response_model=AIClassificationResult).document_type,'invoice')
        self.assertEqual(replay.generate_structured(response_model=AIExtractionResult).seller,'Wrong role value')
        with self.assertRaises(ValueError): replay.generate_structured(response_model=dict)

    def test_manifest_refuses_changed_source_and_missing_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'synthetic.pdf';source.write_bytes(b'synthetic fixture')
            manifest={'permission':'project_generated_synthetic_external_processing_allowed',
                'documents':[{'id':'case','source':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                              'type':'invoice','ground_truth_provenance':'generator_before_predictions'}]}
            path=root/'manifest.json';path.write_text(json.dumps(manifest))
            self.assertEqual(len(prepare_manifest(path)['documents']),1)
            source.write_bytes(b'changed source')
            with self.assertRaises(ValueError): prepare_manifest(path)
            manifest['permission']='unknown';path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): prepare_manifest(path)

    def test_human_study_grade_uses_correctness_not_only_fast_completion(self):
        # Unit fixture only; no participant record or human timing is created.
        truth={'id':'fixture','type':'invoice','fields':{'seller':'Seller'},'route':'Document Review'}
        record={'participant_id':'unit_fixture_not_a_participant','completion_status':'submitted_unscored',
            'arm':'assisted','active_seconds':1,'elapsed_seconds':2,'fields':{'seller':'Buyer'},'route':'Finance'}
        result=grade(record,truth)
        self.assertEqual(result['correct_fields'],0)
        self.assertTrue(result['false_acceptance'])
        self.assertFalse(result['fully_correct'])

    def test_human_study_refuses_invalid_timing_and_incomplete_records(self):
        truth={'id':'fixture','type':'receipt','fields':{'seller':'Shop'},'route':'Expense Processing'}
        record={'participant_id':'unit_fixture_not_a_participant','completion_status':'submitted_unscored',
            'arm':'manual','active_seconds':3,'elapsed_seconds':2,'fields':{'seller':'Shop'},'route':'Expense Processing'}
        with self.assertRaises(ValueError):grade(record,truth)
        record['completion_status']='not_completed'
        with self.assertRaises(ValueError):grade(record,truth)


if __name__=='__main__': unittest.main()

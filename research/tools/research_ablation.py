"""Paired A/B/C/D evaluation on an explicitly approved synthetic manifest.

Default is A only (real RapidOCR, no model calls). --live explicitly opts into
Groq B. C and D reuse exactly B's recorded responses; they do not regenerate them.
Ground truth, source hashes and run configuration are frozen in the new results
directory. Output directories must be new and under results. No original DB writes.
"""
import argparse
from dataclasses import asdict,is_dataclass
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path

from idp.agents.classification_agent import ClassificationAgent
from idp.agents.extraction_agent import ExtractionAgent
from idp.llm.schemas import AIClassificationResult,AIExtractionResult
from idp.ocr.rapidocr_engine import RapidOCREngine
from idp.pipeline.document_pipeline import DocumentPipeline
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
from idp.security import INTERNAL
from research_metrics import score_fields


def parsed_fields(data):
    metadata={'confidence','field_evidence','contract_parties','unsupported_contract_reasons'}
    return {key:value for key,value in data.items() if key not in metadata and value is not None and str(value).strip()}


class RecordedProvider:
    """Replay actual parsed live outputs, never synthesize extraction predictions."""
    def __init__(self,classification,extraction):
        self.classification=classification
        self.extraction=extraction
    def generate_structured(self,*,response_model,**kwargs):
        if response_model is AIClassificationResult: return AIClassificationResult.model_validate(self.classification)
        if response_model is AIExtractionResult: return AIExtractionResult.model_validate(self.extraction)
        raise ValueError('Unexpected replay schema')


class CachedBaseline:
    def __init__(self,result): self.result=result
    def process(self,path): return self.result


def live_provider():
    from idp.llm.provider import GroqProvider
    class RecordingProvider(GroqProvider):
        def __init__(self):
            super().__init__(); self.records=[]; self.parsed={}
        def _request(self,**kwargs):
            started=time.perf_counter()
            try:
                response=super()._request(**kwargs)
            except Exception as error:
                self.records.append({'completed':False,'seconds':time.perf_counter()-started,'error_type':type(error).__name__})
                raise
            self.records.append({'completed':True,'seconds_including_retry_backoff':time.perf_counter()-started,
                'raw_content':response.choices[0].message.content,
                'usage':response.usage.model_dump() if response.usage is not None else None})
            return response
        def generate_structured(self,*args,**kwargs):
            result=super().generate_structured(*args,**kwargs)
            self.parsed[kwargs['response_model'].__name__]=result.model_dump()
            return result
    return RecordingProvider()


def prepare_manifest(path):
    manifest=json.loads(path.read_text(encoding='utf-8-sig'))
    if manifest.get('permission')!='project_generated_synthetic_external_processing_allowed':
        raise ValueError('This pilot only accepts declared project-generated synthetic sources; establish permissions first.')
    cases=manifest['documents']
    if not cases or len({case['id'] for case in cases})!=len(cases):
        raise ValueError('Unique document IDs are required.')
    for case in cases:
        source=(path.parent/case['source']).resolve()
        source.relative_to(path.parent.resolve())
        if hashlib.sha256(source.read_bytes()).hexdigest()!=case['sha256']:
            raise ValueError('Source hash differs from frozen manifest.')
        if case.get('ground_truth_provenance')!='generator_before_predictions':
            raise ValueError('Ground truth provenance is missing.')
        if case['type'] not in {'invoice','purchase_order','receipt','contract'}:
            raise ValueError('Unsupported manifest type.')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--max-documents',type=int,default=6)
    parser.add_argument('--repeats',type=int,default=1)
    args=parser.parse_args()
    if platform.python_version()!='3.14.6': raise SystemExit('Use Python 3.14.6 through uv.')
    if not 1<=args.max_documents<=6 or not 1<=args.repeats<=2:
        raise SystemExit('Pilot is bounded to six documents and two repeats; larger experiments need a reviewed plan.')
    args.output.resolve().relative_to(Path('results').resolve())
    manifest=prepare_manifest(args.manifest)
    cases=manifest['documents'][:args.max_documents]
    if args.output.exists(): raise SystemExit('Use a new results directory; never overwrite experiments.')
    args.output.mkdir(parents=True)
    (args.output/'ground_truth.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    provider=live_provider() if args.live else None
    baseline=DocumentPipeline(RapidOCREngine())
    config={'python':platform.python_version(),'platform':platform.platform(),
            'git_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'git_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
            'lockfile_sha256':hashlib.sha256(Path('uv.lock').read_bytes()).hexdigest(),
            'source_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'mode':'live_B_paired_recorded_response_C_D' if args.live else 'real_OCR_deterministic_A_only',
            'model':provider.model if provider else None,'temperature':0,'repeats':args.repeats,
            'document_count':len(cases),'logical_model_calls_nominal':2*len(cases)*args.repeats if provider else 0,
            'conditions':'Identical cached OCR/layout shared by configurations; fresh isolated D database per repeat. A unsupported contract fields remain missing. C and D reuse B raw parsed model results. Stage totals are not fresh uncached live end-to-end/batch throughput.',
            'limitations':'Small clean English synthetic pilot. No human-ground-truth adjudication or untouched held-out public dataset. Production prompts fixed; source families overlap known schema patterns. No superiority or productivity claim.'}
    (args.output/'configuration.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    predictions=[]; cached={}
    started=time.perf_counter()
    for repeat in range(args.repeats):
        for case in cases:
            source=args.manifest.parent/case['source']
            row={'id':case['id'],'repeat':repeat,'type':case['type'],'completed':False}
            model_start=len(provider.records) if provider else 0
            try:
                if case['id'] not in cached:
                    begin=time.perf_counter(); result=baseline.process(source)
                    cached[case['id']]=(result,time.perf_counter()-begin)
                    (args.output/(case['id']+'_ocr.json')).write_text(json.dumps(asdict(result.ocr),indent=2),encoding='utf-8')
                result,ocr_seconds=cached[case['id']]
                fields=asdict(result.extracted_data) if is_dataclass(result.extracted_data) else {}
                if case['type']=='receipt':
                    fields={('seller' if key=='merchant' else 'issue_date' if key=='date' else key):value for key,value in fields.items()}
                fields.pop('seller_tax_id_evidence',None)
                fields={key:value for key,value in fields.items() if value is not None}
                row['A']={'classification':result.classification.document_class.value,'fields':fields,
                    'comparison':score_fields(case['expected_fields'],fields,case['type'])[0]}
                row['ocr_plus_existing_baseline_seconds']=ocr_seconds
                state={'filename':source.name,'ocr_text':result.ocr.full_text,'ocr_confidence':result.ocr.average_confidence,
                    'baseline_document_type':result.classification.document_class.value,
                    'baseline_fields':asdict(result.extracted_data) if is_dataclass(result.extracted_data) else {},'agent_history':[],'errors':[]}
                if provider:
                    begin=time.perf_counter(); state.update(ClassificationAgent(provider).run(state))
                    # Existing prompt obtains raw response; B below intentionally discards postprocessing.
                    ExtractionAgent(provider).run(state)
                    row['B_model_seconds_including_retries']=time.perf_counter()-begin
                    classification=provider.parsed['AIClassificationResult']
                    extraction=provider.parsed.get('AIExtractionResult')
                    if state['document_type']=='unknown':
                        extraction=AIExtractionResult(confidence=0).model_dump()
                    raw=parsed_fields(extraction)
                    row['B']={'classification':state['document_type'],'raw_parsed':extraction,'fields':raw,
                        'comparison':score_fields(case['expected_fields'],raw,case['type'])[0]}
                    replay=RecordedProvider(classification,extraction)
                    begin=time.perf_counter(); row['C']=ExtractionAgent(replay).run(state)
                    row['C_postprocessing_seconds']=time.perf_counter()-begin
                    row['C']['comparison']=score_fields(case['expected_fields'],row['C']['extracted_fields'],case['type'])[0]
                    pipeline=AgenticDocumentPipeline(args.output/f'repeat_{repeat}.db',baseline=CachedBaseline(result),llm=replay,_capability=INTERNAL)
                    begin=time.perf_counter(); processed=pipeline.process(source)
                    row['D_graph_persistence_seconds_with_cached_OCR_recorded_model']=time.perf_counter()-begin
                    row['D']=processed
                    decision=processed['state']
                    row['routing_correct']=decision['workflow_status']==case['expected_status'] and decision['assigned_department']==case['expected_department']
                    row['policy_version_id']=decision.get('policy_version_id')
                    row['policy_config']=decision.get('policy_config')
                    (args.output/f"{case['id']}_repeat_{repeat}_parsed_classification.json").write_text(json.dumps(classification,indent=2),encoding='utf-8')
                row['completed']=True
            except Exception as error:
                row['error_type']=type(error).__name__
            if provider: row['model_response_records']=provider.records[model_start:]
            predictions.append(row)
            (args.output/'predictions.json').write_text(json.dumps(predictions,indent=2),encoding='utf-8')
            print(json.dumps({'case':case['id'],'repeat':repeat,'completed':row['completed'],'mode':config['mode']}),flush=True)
            if provider and not row['completed']:
                break
            if provider: time.sleep(5)
        if provider and predictions and not predictions[-1]['completed']: break
    (args.output/'execution.json').write_text(json.dumps({'wall_seconds_excluding_initial_provider_OCR_construction_including_pacing':time.perf_counter()-started,
        'attempted':len(predictions),'completed':sum(row['completed'] for row in predictions),'API_usage': [record['usage'] for record in provider.records if record.get('usage')] if provider else [],
        'human_time_measured':False,'batch_throughput_measured':False},indent=2),encoding='utf-8')


if __name__=='__main__': main()

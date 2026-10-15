"""Measure real batch/SQLite/cache work with recorded live outputs and cached OCR.

This is not new live Groq/OCR throughput. Repeated source bytes are deliberately
cache workloads, not independent documents or industrial scale evidence.
"""
import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path
from types import SimpleNamespace

from idp.security import INTERNAL
from idp.batch.service import BatchService
from idp.storage.repository import DocumentRepository
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
from idp.models.invoice import InvoiceData
from idp.models.receipt import ReceiptData
from idp.models.purchase_order import PurchaseOrderData
from research_ablation import RecordedProvider


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.resolve().relative_to(Path('results').resolve())
    if args.output.exists(): raise SystemExit('Use a new output directory.')
    records=json.loads(args.predictions.read_text())
    manifest=json.loads(args.manifest.read_text())
    by_id={row['id']:row for row in records if row.get('completed') and 'D' in row}
    samples=[case for case in manifest['documents'] if case['id'] in by_id]
    if not samples: raise SystemExit('No recorded live cases available.')
    entries={case['sha256']:by_id[case['id']] for case in samples}
    calls=[]
    class Replay:
        current=None
        def generate_structured(self,**kwargs):
            calls.append(kwargs['response_model'].__name__)
            row=self.current
            state=row['D']['state']
            return RecordedProvider({'document_type':row['B']['classification'],
                'confidence':state['classification_confidence'],'evidence':state.get('classification_evidence',[])},
                row['B']['raw_parsed']).generate_structured(**kwargs)
    replay=Replay()
    class Baseline:
        def process(self,path):
            row=entries[hashlib.sha256(Path(path).read_bytes()).hexdigest()]
            replay.current=row
            state=row['D']['state'];kind=state['baseline_document_type']
            cls={'invoice':InvoiceData,'purchase_order':PurchaseOrderData,'receipt':ReceiptData}.get(kind)
            return SimpleNamespace(classification=SimpleNamespace(document_class=SimpleNamespace(value=kind)),
                extracted_data=cls(**state.get('baseline_fields',{})) if cls else None,
                ocr=SimpleNamespace(full_text=state['ocr_text'],average_confidence=state['ocr_confidence']))
    args.output.mkdir(parents=True)
    rows=[]
    for size in (5,10,20):
        repo=DocumentRepository(args.output/f'batch_{size}.db',_capability=INTERNAL)
        service=BatchService(repo)
        files=[]
        for index in range(size):
            case=samples[index%len(samples)]
            files.append((str(index)+'_'+case['source'],(args.manifest.parent/case['source']).read_bytes()))
        before=len(calls);start=time.perf_counter()
        batch=service.submit(files,request_key=f'replay-{size}',name=f'Recorded response/cache test {size}')
        pipeline=AgenticDocumentPipeline(repo.db_path,baseline=Baseline(),llm=replay,_capability=INTERNAL)
        service.run(lambda:pipeline,batch,max_items=size)
        wall=time.perf_counter()-start
        items=service.items(batch); times=[item['duration_seconds'] for item in items]
        rows.append({'submitted':size,'source_families':len(set(case['source_family'] for case in samples[:min(size,len(samples))])),
            'unique_source_bytes':min(size,len(samples)),'duplicates':sum(item['state']=='duplicate' for item in items),
            'failures':sum(item['state']=='failed' for item in items),'wall_seconds':wall,
            'cached_replay_documents_per_minute':size/wall*60,
            'median_seconds':statistics.median(times),'p95_nearest_rank_seconds':sorted(times)[__import__('math').ceil(.95*len(times))-1],
            'variance_population':statistics.pvariance(times),'recorded_response_calls':len(calls)-before,
            'new_live_api_calls':0,'new_OCR_calls':0,'items':[{'state':item['state'],'duration_seconds':item['duration_seconds']} for item in items]})
        first=samples[0]
        start=time.perf_counter()
        forced=pipeline.process(args.manifest.parent/first['source'],force_reprocess=True)
        rows[-1]['forced_reprocess']={'reprocessed':forced['reprocessed'],'duplicate':forced['duplicate'],'seconds':time.perf_counter()-start,'new_API_calls':0}
    result={'conditions':'Actual local batch submission, source hashing, graph, duplicate cache, forced reprocessing and SQLite work; cached OCR and recorded live provider responses. Not end-to-end live inference throughput.',
        'limitations':'Five/ten/twenty items reuse only six synthetic source byte streams and four source families. Cache-heavy local work cannot establish industrial scalability. No concurrent load or fresh API retry overhead.',
        'batches':rows}
    (args.output/'metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'batches':len(rows),'items':sum(row['submitted'] for row in rows),'failures':sum(row['failures'] for row in rows),'new_API_calls':0}))


if __name__=='__main__': main()

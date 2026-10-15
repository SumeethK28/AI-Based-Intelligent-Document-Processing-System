"""Opt-in live RapidOCR/Groq batch evaluation. Never prints raw provider errors."""
from idp.security import INTERNAL
import argparse
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from idp.batch.service import BatchService
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
from idp.storage.repository import DocumentRepository
from idp.utils.money import parse_money


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',default=None)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = Path(args.output) if args.output else root/'results'/('milestone3_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S'))
    output.mkdir(parents=True,exist_ok=False)
    database = output/'live.db'
    service = BatchService(DocumentRepository(database, _capability=INTERNAL))
    samples = root/'data/samples/cross_document'
    files = [(name,(samples/name).read_bytes()) for name in ('invoice_matching.pdf','purchase_order_1023.pdf')]
    batch = service.submit(files,request_key='controlled-live-invoice-first',name='Live invoice before PO')
    start = time.perf_counter()
    service.run(lambda:AgenticDocumentPipeline(database, _capability=INTERNAL),batch)
    elapsed = time.perf_counter()-start
    summary = service.summary(batch)
    checks = []
    for item in service.items(batch):
        state = json.loads(item['result_snapshot']) if item['result_snapshot'] else {}
        expected = {'invoice_number':'INV-501','seller':'ABC Technologies','client':'XYZ Company','issue_date':'10/10/2026','total':'INR 42000.00','po_reference':'PO-1023'} if item['filename'].startswith('invoice') else {'po_number':'PO-1023','vendor':'ABC Technologies','buyer':'XYZ Company','order_date':'10/10/2026','total':'INR 42000.00'}
        fields = state.get('extracted_fields',{})
        field_checks = {key:(parse_money(fields.get(key))==parse_money(value) if key=='total' else fields.get(key)==value) for key,value in expected.items()}
        checks.append({'filename':item['filename'],'actual_fields':fields,'expected_fields':expected,'field_checks':field_checks,
                       'validation_passed':state.get('validation_passed'),'validation_errors':state.get('validation_errors'),
                       'cross_document_status':state.get('cross_document_status'),'workflow_status':state.get('workflow_status'),
                       'duration_seconds':item['duration_seconds'],'item_state':item['state']})
    passed = (summary['counts']['failed']==0 and len(checks)==2 and all(all(row['field_checks'].values()) and row['validation_passed'] and row['workflow_status']=='pending_department_review' for row in checks)
              and checks[0]['cross_document_status']=='matched')
    report = {'python':platform.python_version(),'model':os.getenv('GROQ_MODEL','openai/gpt-oss-120b'),'conditions':'Real RapidOCR and configured Groq; new isolated database; serial invoice before PO; two synthetic PDFs; no mocks',
              'batch_id':batch,'database':str(database),'wall_seconds':elapsed,'successful_items':2-summary['counts']['failed'],
              'failed_items':summary['counts']['failed'],'checks_passed':passed,'documents':checks,'summary':summary}
    (output/'live_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'batch_id':batch,'wall_seconds':elapsed,'checks_passed':passed,
                      'items':[{key:row[key] for key in ('filename','item_state','validation_passed','cross_document_status','workflow_status','duration_seconds')} for row in checks]},indent=2))
    raise SystemExit(0 if passed else 1)

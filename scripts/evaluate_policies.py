"""Reproducible deterministic policy comparison; no live model or OCR accuracy claim."""
import argparse
import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter

from idp.agents.validation_agent import ValidationAgent
from idp.agents.anomaly_agent import AnomalyDetectionAgent
from idp.agents.cross_document_agent import CrossDocumentAgent
from idp.agents.routing_agent import WorkflowRoutingAgent
from idp.policy.schema import DEFAULT
from idp.policy.service import PolicyService
from idp.storage.repository import DocumentRepository
from idp.storage.intelligence import IntelligenceQueries


def fixture(kind,fields,**extras):
    return {'document_type':kind,'extracted_fields':fields,'field_evidence':dict(fields),
        'ocr_text':'\n'.join(fields.values()),'evidence_warnings':[],'contract_parties':[fields[key] for key in ('party_a','party_b') if fields.get(key)],
        'agent_history':[],'errors':[],**extras}


def check(repository,state,config=None,version_id=None):
    state=copy.deepcopy(state)
    for key in ('policy_config','policy_version_id','rule_outcomes','policy_failed_rules','policy_evaluation_error'):
        state.pop(key,None)
    if config is not None:
        state.update(policy_config=config,policy_version_id=version_id)
    start=perf_counter()
    state.update(ValidationAgent().run(state))
    state.update(AnomalyDetectionAgent().run(state))
    state.update(CrossDocumentAgent(repository).run(state))
    if config is not None:
        state=PolicyService(repository).evaluate(state)
    state.update(WorkflowRoutingAgent().run(state))
    return state,(perf_counter()-start)*1000


def evaluate(output):
    output.mkdir(parents=True,exist_ok=False)
    repository=DocumentRepository(output/'uat.db')
    service=PolicyService(repository)
    po=fixture('purchase_order',{'po_number':'PO-EVAL','order_date':'2026-10-01','vendor':'Supplier','total':'INR 100.00'})
    source=output/'po_source.txt'; source.write_text('Synthetic evaluation PO; not a business transaction.')
    po,_=check(repository,po,DEFAULT,1)
    repository.save_processed_document(source,source.name,po)
    invoice={'invoice_number':'INV-EVAL','issue_date':'2026-10-01','seller':'Supplier','client':'Buyer','total':'INR 100.00'}
    contract={'contract_title':'Service Agreement','party_a':'Alpha','party_b':'Beta','effective_date':'2026-10-01','expiration_date':'2027-10-01'}
    cases=[
        ('missing_po',fixture('invoice',invoice),True,False),
        ('matched_po',fixture('invoice',{**invoice,'invoice_number':'INV-MATCH','po_reference':'PO-EVAL'}),True,True),
        ('within_proposed_tolerance',fixture('invoice',{**invoice,'invoice_number':'INV-TOL','po_reference':'PO-EVAL','total':'INR 100.50'}),False,True),
        ('outside_proposed_tolerance',fixture('invoice',{**invoice,'invoice_number':'INV-OVER','po_reference':'PO-EVAL','total':'INR 100.51'}),False,False),
        ('wrong_currency',fixture('invoice',{**invoice,'invoice_number':'INV-CURRENCY','po_reference':'PO-EVAL','total':'USD 100.00'}),False,False),
        ('missing_seller',fixture('invoice',{key:value for key,value in invoice.items() if key!='seller'}),False,False),
        ('unverified_evidence',fixture('invoice',invoice,field_evidence={}),False,False),
        ('high_value_usd',fixture('receipt',{'seller':'Shop','issue_date':'2026-10-01','total':'USD 1001.00'}),True,False),
        ('valid_receipt',fixture('receipt',{'seller':'Shop','issue_date':'2026-10-01','total':'INR 20.00'}),True,True),
        ('receipt_arithmetic',fixture('receipt',{'seller':'Shop','issue_date':'2026-10-01','total':'INR 20.00','subtotal':'INR 10.00','tax':'INR 1.00'}),False,False),
        ('valid_contract',fixture('contract',contract),True,True),
        ('missing_contract_expiration',fixture('contract',{key:value for key,value in contract.items() if key!='expiration_date'}),True,False),
        ('unsupported_contract',fixture('contract',contract,unsupported_contract_reasons=['Multi-party structure unsupported']),False,False),
        ('wrong_supplier',fixture('invoice',{**invoice,'invoice_number':'INV-VENDOR','po_reference':'PO-EVAL','seller':'Other Supplier'}),False,False),
    ]
    proposed=copy.deepcopy(DEFAULT)
    proposed.update(require_po_reference=True,po_tolerance='0.50',require_contract_expiration=True)
    proposed['high_value_thresholds']['USD']='1000'
    version=service.draft(proposed,actor='prototype:evaluator',reason='Synthetic comparison policy, not production activation')
    metrics=[]
    for index,(name,state,baseline_expected,policy_expected) in enumerate(cases):
        # Give each scenario a distinct source and business number for deterministic independence.
        source=output/(name+'.txt'); source.write_text('SYNTHETIC POLICY FIXTURE '+name+'\n'+state['ocr_text'])
        if state['document_type']=='invoice':
            old=state['extracted_fields'].get('invoice_number')
            state['extracted_fields']['invoice_number']='CASE-'+str(index)
            state['field_evidence']['invoice_number']='CASE-'+str(index)
            state['ocr_text']=state['ocr_text'].replace(old,'CASE-'+str(index)) if old else state['ocr_text']
        baseline,baseline_ms=check(repository,state)
        policy,policy_ms=check(repository,state,proposed,version)
        repetitions=[check(repository,state,proposed,version)[1] for _ in range(10)]
        eligible=lambda result:result['workflow_status']=='pending_department_review'
        metrics.append({'scenario':name,'kind':state['document_type'],'baseline_expected_eligible':baseline_expected,
            'policy_expected_eligible':policy_expected,'baseline_eligible':eligible(baseline),'policy_eligible':eligible(policy),
            'baseline_workflow':baseline['workflow_status'],'policy_workflow':policy['workflow_status'],
            'baseline_latency_ms':baseline_ms,'policy_total_checks_latency_ms':policy_ms,'policy_repeat_median_ms':median(repetitions),
            'rule_engine_latency_ms':policy['policy_latency_ms'],'failed_rules':policy['policy_failed_rules'],
            'explanation_complete':bool(policy['rule_outcomes']) and all(item['policy_version_id']==version for item in policy['rule_outcomes'])})
        # UAT repository deliberately retains baseline-policy results; previews do not rewrite these.
        persisted,_=check(repository,state,DEFAULT,1)
        repository.save_processed_document(source,source.name,persisted)
    def rates(prefix):
        positives=sum(not row[prefix+'_expected_eligible'] for row in metrics)
        negatives=len(metrics)-positives
        false_accept=sum(row[prefix+'_eligible'] and not row[prefix+'_expected_eligible'] for row in metrics)
        false_escalation=sum(not row[prefix+'_eligible'] and row[prefix+'_expected_eligible'] for row in metrics)
        return {'expected_violations':positives,'expected_eligible':negatives,'false_acceptances':false_accept,'false_escalations':false_escalation,
            'false_acceptance_rate':false_accept/positives if positives else None,'false_escalation_rate':false_escalation/negatives if negatives else None,
            'detected_expected_violations':positives-false_accept,'manual_review_documents':sum(not row[prefix+'_eligible'] for row in metrics)}
    # Real original DB audit and migration on a consistent COPY only.
    original=Path('data/idp.db')
    migration={}
    if original.exists():
        before_hash=hashlib.sha256(original.read_bytes()).hexdigest()
        copy_path=output/'migration_copy.db'
        with closing(sqlite3.connect(f'file:{original.resolve().as_posix()}?mode=ro',uri=True)) as db:
            before={table:db.execute('SELECT * FROM '+table).fetchall() for table in ('documents','processing_runs','processing_versions','review_events') if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone()}
            with closing(sqlite3.connect(copy_path)) as target: db.backup(target)
        migrated=DocumentRepository(copy_path)
        with migrated.connect() as db:
            preserved=all([tuple(row)[:len(records[0])] for row in db.execute('SELECT * FROM '+table)]==records if records else db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0 for table,records in before.items())
            integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
            foreign_errors=len(db.execute('PRAGMA foreign_key_check').fetchall())
        migration={'original_sha256_before':before_hash,'original_sha256_after':hashlib.sha256(original.read_bytes()).hexdigest(),
            'legacy_tables_preserved':preserved,'legacy_row_counts':{table:len(records) for table,records in before.items()},
            'copy_integrity':integrity,'foreign_key_errors':foreign_errors,'backups':[path.name for path in output.glob('migration_copy.db.before_*.db')]}
        assert preserved and integrity=='ok' and foreign_errors==0 and migration['original_sha256_after']==before_hash
    report={'conditions':'Deterministic synthetic OCR text and known structured fields; no RapidOCR or Groq calls. Baseline uses original default validation/anomaly/cross/routing semantics plus strengthened PO restriction guard; proposed policy adds PO-reference/expiration requirements and currency threshold, and allows a 0.50 same-currency PO tolerance.',
        'dataset_size':len(cases),'latency_repeats_per_document':10,'baseline':rates('baseline'),'policy':rates('policy'),
        'policy_config':proposed,'policy_version_id':version,'documents':metrics,'migration':migration,
        'explanation_completeness':sum(row['explanation_complete'] for row in metrics)/len(metrics),
        'limitations':'Small constructed rule dataset, not extraction/classification accuracy or industrial workload evidence. Latencies are local isolated deterministic checks including SQLite reads, not model speed or manual-effort savings. Workload counts depend on chosen policies; no improvement claim.'}
    (output/'metrics.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (output/'analytics.json').write_text(json.dumps(IntelligenceQueries(repository).report(),indent=2),encoding='utf-8')
    rows='\n'.join(f"| {row['scenario']} | {row['baseline_expected_eligible']} / {row['baseline_eligible']} | {row['policy_expected_eligible']} / {row['policy_eligible']} | {', '.join(row['failed_rules']) or 'None'} |" for row in metrics)
    (output/'evaluation_report.md').write_text('# Milestone 5 deterministic policy evaluation\n\n'+report['conditions']+'\n\nDataset: '+str(len(cases))+' scenarios. Provider calls: 0. OCR calls: 0.\n\n| Scenario | Baseline expected / observed eligible | Policy expected / observed eligible | Rules causing escalation |\n|---|---|---|---|\n'+rows+'\n\n'+json.dumps({'baseline':report['baseline'],'policy':report['policy'],'migration':migration},indent=2)+'\n\n'+report['limitations'],encoding='utf-8')
    assert all(row['baseline_eligible']==row['baseline_expected_eligible'] and row['policy_eligible']==row['policy_expected_eligible'] for row in metrics)
    print(json.dumps({'output':str(output.resolve()),'scenarios':len(cases),'baseline':report['baseline'],'policy':report['policy'],'explanation_completeness':report['explanation_completeness']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('results')/('milestone5_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')))
    evaluate(parser.parse_args().output)

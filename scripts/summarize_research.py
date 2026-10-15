"""Summarize bounded experiments; optional matplotlib figures are local artifacts."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
from research_metrics import score_fields,wilson


def write_csv(path,rows):
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]) if rows else ['case'])
        writer.writeheader();writer.writerows(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--plots',action='store_true')
    args=parser.parse_args()
    args.output.resolve().relative_to(Path('results').resolve())
    if args.output.exists():raise SystemExit('Choose a new output directory.')
    root=args.root;manifest=json.loads((root/'pilot_dataset/manifest.json').read_text())
    truth={row['id']:row for row in manifest['documents']}
    pred=json.loads((root/'pilot_live/predictions.json').read_text())
    repeat=json.loads((root/'pilot_repeat_po_invoice/predictions.json').read_text())
    stress=json.loads((root/'stress_A_only/predictions.json').read_text())
    stress_truth={row['id']:row for row in json.loads((root/'stress_dataset/manifest.json').read_text())['documents']}
    completed=[row for row in pred if row['completed']]
    fields=[];aggregates=[];decisions=[]
    for configuration in ('A','B','C','D'):
        groups={}
        for row in completed:
            expected=truth[row['id']]
            actual=row[configuration]['fields'] if configuration in ('A','B') else row['C']['extracted_fields'] if configuration=='C' else row['D']['state']['extracted_fields']
            comparisons,counts=score_fields(expected['expected_fields'],actual,expected['type'])
            for comparison in comparisons:fields.append({'case':row['id'],'configuration':configuration,'type':expected['type'],**comparison})
            group=groups.setdefault(expected['type'],{'documents':0,'slots':0,'tp':0,'fp':0,'fn':0,'classification_correct':0,'unannotated_predictions':0})
            group['documents']+=1;group['slots']+=counts['annotated_slots']
            for key in ('tp','fp','fn'):group[key]+=counts[key]
            classification=row['A']['classification'] if configuration=='A' else row['B']['classification'] if configuration in ('B','C') else row['D']['state']['document_type']
            group['classification_correct']+=classification==expected['type']
            group['unannotated_predictions']+=len(counts['unannotated_predictions'])
        for kind,group in groups.items():
            tp,fp,fn=group['tp'],group['fp'],group['fn']
            aggregates.append({'configuration':configuration,'type':kind,**group,
                'precision_annotated_present':tp/(tp+fp) if tp+fp else None,
                'recall_annotated_present':tp/(tp+fn) if tp+fn else None,
                'f1_annotated_present':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
                'baseline_extractor_supported':kind!='contract' or configuration!='A'})
    for row in completed:
        expected=truth[row['id']];state=row['D']['state']
        unsafe=bool(expected['expected_violations']);accepted=state['workflow_status']=='pending_department_review'
        decisions.append({'case':row['id'],'expected_status':expected['expected_status'],'actual_status':state['workflow_status'],
            'expected_department':expected['expected_department'],'actual_department':state['assigned_department'],
            'correct':row['routing_correct'],'validation_passed':state['validation_passed'],
            'cross_status':state['cross_document_status'],'expected_unsafe':unsafe,
            'false_acceptance':unsafe and accepted,'false_escalation':not unsafe and not accepted,
            'policy_version_id':state.get('policy_version_id'),'fallback_used':','.join(state.get('fallback_used',[]))})
    stress_rows=[]
    for row in stress:
        expected=stress_truth[row['id']]
        if row['completed']:
            comparison,counts=score_fields(expected['expected_fields'],row['A']['fields'],expected['type'])
            stress_rows.append({'case':row['id'],'type':expected['type'],'completed':True,'classification_correct':row['A']['classification']==expected['type'],
                'correct':counts['tp'],'slots':counts['annotated_slots'],'seconds_real_OCR_plus_baseline':row['ocr_plus_existing_baseline_seconds'],
                'known_absent_false_predictions':sum(bool(row['A']['fields'].get(field)) for field in expected.get('known_absent_fields',[]))})
        else:stress_rows.append({'case':row['id'],'type':expected['type'],'completed':False,'classification_correct':False,'correct':0,'slots':len(expected['expected_fields']),'seconds_real_OCR_plus_baseline':None,'known_absent_false_predictions':None})
    repeat_rows=[]
    for row in repeat:
        first=next(original for original in pred if original['id']==row['id'])
        repeat_rows.append({'case':row['id'],'completed':row['completed'],'B_fields_equal':row.get('B',{}).get('fields')==first.get('B',{}).get('fields'),
            'classification_equal':row.get('B',{}).get('classification')==first.get('B',{}).get('classification'),
            'first_B_seconds':first.get('B_model_seconds_including_retries'),'second_B_seconds':row.get('B_model_seconds_including_retries')})
    records=[record for row in pred+repeat for record in row.get('model_response_records',[])]
    usage=[record['usage'] for record in records if record.get('usage')]
    live={'response_groups':len(records),'successful_responses':sum(record.get('completed',False) for record in records),
        'prompt_tokens':sum(item.get('prompt_tokens',0) for item in usage),'completion_tokens':sum(item.get('completion_tokens',0) for item in usage),
        'total_tokens':sum(item.get('total_tokens',0) for item in usage),
        'usage_responses':len(usage),'http_retry_attempt_count':'not separately instrumented; response-group times include bounded retries',
        'cost_estimate':None,'cost_limitation':'No billed price/rate verified; no cost-saving claim.'}
    stage_rows=[{'case':row['id'],'OCR_plus_deterministic_baseline':row['ocr_plus_existing_baseline_seconds'],
        'B_model_including_retry':row['B_model_seconds_including_retries'],
        'C_postprocessing':row['C_postprocessing_seconds'],'D_cached_graph_and_persistence':row['D_graph_persistence_seconds_with_cached_OCR_recorded_model']} for row in completed]
    latency={key:{'n':len(stage_rows),'median':statistics.median([row[key] for row in stage_rows]),
        'p95_nearest_rank':max(row[key] for row in stage_rows),'variance_population':statistics.pvariance([row[key] for row in stage_rows])} for key in stage_rows[0] if key!='case'}
    args.output.mkdir(parents=True)
    write_csv(args.output/'fields.csv',fields);write_csv(args.output/'ablation_by_type.csv',aggregates)
    write_csv(args.output/'routing.csv',decisions);write_csv(args.output/'stress_A.csv',stress_rows)
    write_csv(args.output/'repeat_variability.csv',repeat_rows);write_csv(args.output/'stage_seconds.csv',stage_rows)
    summary={'pilot_unique_documents':len(pred),'pilot_completed':len(completed),'source_families':len(set(row['source_family'] for row in manifest['documents'])),
        'configurations':'A fresh real OCR/baseline; B real Groq; C/D paired replay of B, not independent live calls',
        'ablation_by_type':aggregates,'routing_correct':sum(row['correct'] for row in decisions),'routing_evaluated':len(decisions),
        'classification_live_correct':sum(row['B']['classification']==truth[row['id']]['type'] for row in completed),
        'classification_wilson95_descriptive':wilson(sum(row['B']['classification']==truth[row['id']]['type'] for row in completed),len(completed)),
        'false_acceptance_count':sum(row['false_acceptance'] for row in decisions),'unsafe_denominator':sum(row['expected_unsafe'] for row in decisions),
        'false_escalation_count':sum(row['false_escalation'] for row in decisions),'eligible_denominator':sum(not row['expected_unsafe'] for row in decisions),
        'fallback_fields_used':sum(len(row['C'].get('fallback_used',[])) for row in completed),
        'live_usage':live,'stage_latency':latency,'repeat_cases':repeat_rows,'stress_A':stress_rows,
        'limitations':'Synthetic development pilot, correlated source templates/families, two repeated sources only. No measured industrial productivity, broad real-world accuracy, independent evidence annotation, API retry attribution, or scalable live inference throughput. No layout fallback benefit observed because none was used.'}
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    fingerprints={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [Path('uv.lock'),*Path('src/idp').rglob('*.py'),*Path('scripts').glob('*research*.py')]}
    (args.output/'code_fingerprints.json').write_text(json.dumps(fingerprints,indent=2),encoding='utf-8')
    # Blank human-study sheet: no fabricated measurements.
    with (args.output/'human_study_template.csv').open('w',encoding='utf-8') as stream:
        stream.write('participant_id,case_family,arm,order,active_seconds,elapsed_seconds,expected_fields,correct_fields,corrections,escalations,false_approval,exception_seconds,workload_rating,completion_status\n')
    if args.plots:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
        for ax,kinds,title in [(axes[0],{'invoice','purchase_order','receipt'},'Supported baseline tasks'),(axes[1],{'contract'},'Contract metadata (A unsupported)')]:
            rates=[];labels=[]
            for configuration in ('A','B','C'):
                group=[row for row in aggregates if row['configuration']==configuration and row['type'] in kinds]
                correct=sum(row['tp'] for row in group);n=sum(row['slots'] for row in group)
                rates.append(correct/n);labels.append(f'{configuration}\n{correct}/{n}')
            ax.bar(labels,rates,color=['#8694a4','#3176b7','#1d8a70']);ax.set_ylim(0,1.1)
            ax.set_ylabel('Correct annotated present fields / slots');ax.set_title(title)
        fig.suptitle('Six synthetic pilot documents; B/C share the same live model outputs')
        fig.savefig(args.output/'ablation.png',dpi=180);fig.savefig(args.output/'ablation.pdf');plt.close(fig)
        fig,ax=plt.subplots(figsize=(9,4),layout='constrained')
        stages=['OCR_plus_deterministic_baseline','B_model_including_retry','C_postprocessing','D_cached_graph_and_persistence']
        ax.boxplot([[row[key] for row in stage_rows] for key in stages],tick_labels=['Real OCR + baseline','Real Groq B','C postprocess','D cached graph + SQLite'],showmeans=True)
        ax.set_ylabel('Measured seconds per source (n=6)');ax.set_title('Measured stages; cached replay timings are not live inference latency')
        fig.savefig(args.output/'stage_latency.png',dpi=180);fig.savefig(args.output/'stage_latency.pdf');plt.close(fig)
    print(json.dumps({'pilot_completed':len(completed),'routing_correct':summary['routing_correct'],'usage':live,'stress_completed':sum(row['completed'] for row in stress_rows)},indent=2))


if __name__=='__main__':main()

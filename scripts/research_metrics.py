"""Reanalyse saved predictions without OCR/API calls or database writes.

Field metrics are restricted to annotated, present ground-truth slots. An unknown
extra is not labelled a hallucination without a complete absent-field annotation.
This does not turn historical runs into a new controlled ablation experiment.
"""
import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
from pathlib import Path

from idp.agents.validation_agent import ValidationAgent
from idp.utils.evidence import normalize_ocr_text
from idp.utils.money import parse_money


def equivalent(field, actual, expected):
    if actual is None or not str(actual).strip():
        return False
    if field in ValidationAgent.AMOUNT_FIELDS:
        left, right = parse_money(actual), parse_money(expected)
        return left is not None and right is not None and left == right
    # Preserve printed dates: ambiguous day/month formats are not silently swapped.
    return normalize_ocr_text(actual) == normalize_ocr_text(expected)


def wilson(success, total):
    if total == 0:
        return None
    z = 1.959963984540054
    p = success / total
    denominator = 1 + z*z/total
    centre = (p + z*z/(2*total))/denominator
    radius = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/denominator
    return [max(0, centre-radius), min(1, centre+radius)]


def score_fields(expected, actual, kind):
    comparisons = []
    required = ValidationAgent.REQUIRED_FIELDS.get(kind, [])
    optional = ValidationAgent.OPTIONAL_FIELDS.get(kind, [])
    for field, value in expected.items():
        if value is None:
            raise ValueError('Use a separate explicit absent-field annotation, not null present ground truth.')
        prediction = actual.get(field)
        present = prediction is not None and bool(str(prediction).strip())
        correct = equivalent(field, prediction, value)
        comparisons.append({'field':field,'expected':value,'actual':prediction,'present':present,
                            'correct':correct,'mandatory':field in required,'optional':field in optional})
    tp = sum(row['correct'] for row in comparisons)
    fp = sum(row['present'] and not row['correct'] for row in comparisons)
    fn = sum(not row['correct'] for row in comparisons)
    return comparisons, {'tp':tp,'fp':fp,'fn':fn,'annotated_slots':len(comparisons),
                         'unannotated_predictions':{key:value for key,value in actual.items() if key not in expected}}


def analyse(report):
    rows, confusion, documents = [], {}, []
    for entry in report.get('documents', []):
        if not entry.get('completed'):
            documents.append({'case':entry.get('filename',entry.get('name')),'completed':False,
                              'error_type':entry.get('error_type')})
            continue
        state = entry['state']
        expected = entry.get('expected',entry.get('expected_fields',{}))
        kind = entry.get('expected_classification',entry.get('type'))
        fields, counts = score_fields(expected,state.get('extracted_fields',{}),kind)
        name = entry.get('filename',entry.get('name'))
        predicted = state.get('document_type','unknown')
        confusion.setdefault(kind,{})[predicted] = confusion.get(kind,{}).get(predicted,0)+1
        for field in fields:
            evidence = state.get('field_evidence',{}).get(field['field'],'')
            text = normalize_ocr_text(state.get('ocr_text',''))
            fragments = [normalize_ocr_text(part) for part in str(evidence).splitlines() if part.strip()]
            value_supported = field['present'] and normalize_ocr_text(field['actual']) in text
            # Text-support proxy only, not an independently adjudicated role label.
            evidence_supported = bool(fragments) and all(part in text for part in fragments)
            rows.append({'case':name,'document_type':kind,**field,
                         'value_and_evidence_supported_proxy':bool(value_supported and evidence_supported),
                         'fallback':field['field'] in state.get('fallback_used',[])})
        expected_route = entry.get('expected_routing')
        expected_department = entry.get('expected_department')
        if expected_route is None and expected_department:
            expected_route = 'manual_review' if expected_department=='Document Review' else 'pending_department_review'
        route_correct = None if expected_route is None else state.get('workflow_status')==expected_route and state.get('assigned_department')==expected_department
        documents.append({'case':name,'completed':True,'classification_correct':predicted==kind,
                          'expected_route':expected_route,'actual_route':state.get('workflow_status'),
                          'routing_correct':route_correct,'department':state.get('assigned_department'),
                          'seconds_historical':entry.get('seconds'),'counts':counts,
                          'fallback_used':state.get('fallback_used',[]),
                          'raw_model_saved':entry.get('raw_model_extraction') is not None})
    completed = [row for row in documents if row['completed']]
    tp=sum(row['counts']['tp'] for row in completed)
    fp=sum(row['counts']['fp'] for row in completed)
    fn=sum(row['counts']['fn'] for row in completed)
    correct=sum(row['classification_correct'] for row in completed)
    times=[row['seconds_historical'] for row in completed if row['seconds_historical'] is not None]
    mandatory=[row for row in rows if row['mandatory']]
    optional=[row for row in rows if row['optional']]
    return {'attempted':len(documents),'completed':len(completed),'classification_correct':correct,
            'classification_wilson95':wilson(correct,len(completed)),'confusion':confusion,
            'annotated_present_fields':{'tp':tp,'fp':fp,'fn':fn,
                'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
                'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None},
            'mandatory_annotated_present':{'slots':len(mandatory),'present':sum(row['present'] for row in mandatory),'correct':sum(row['correct'] for row in mandatory)},
            'optional_annotated_present':{'slots':len(optional),'correct':sum(row['correct'] for row in optional)},
            'historical_latency':{'count':len(times),'median':statistics.median(times) if times else None,
                'mean':statistics.mean(times) if times else None,'variance_population':statistics.pvariance(times) if times else None,
                'p95_nearest_rank':sorted(times)[math.ceil(.95*len(times))-1] if times else None},
            'documents':documents}, rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if platform.python_version()!='3.14.6':
        raise SystemExit('Use Python 3.14.6 through uv.')
    if args.output.resolve()==args.input.resolve() or args.output.exists():
        raise SystemExit('Choose a new output directory; previous results are never overwritten.')
    content=json.loads(args.input.read_text(encoding='utf-8-sig'))
    metrics,rows=analyse(content)
    args.output.mkdir(parents=True)
    result={'mode':'historical_prediction_reanalysis_no_new_model_or_ocr_calls',
            'input':str(args.input),'input_sha256':hashlib.sha256(args.input.read_bytes()).hexdigest(),
            'python':platform.python_version(),'model_historical':content.get('model'),
            'conditions_historical':content.get('conditions'),
            'limitations':'Annotated present slots only; unannotated extras remain unknown, not hallucinations. Wilson interval is descriptive under an iid model, not evidence this convenience sample is representative. Fields within a document are correlated; no pooled field confidence interval. No human productivity or batch throughput inferred. Raw model output may be unavailable; post-fallback fields cannot reconstruct it.',
            'metrics':metrics}
    (args.output/'metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with (args.output/'fields.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]) if rows else ['case'])
        writer.writeheader(); writer.writerows(rows)
    print(json.dumps({'mode':result['mode'],'documents':metrics['completed'],'fields':metrics['annotated_present_fields']},indent=2))


if __name__=='__main__': main()

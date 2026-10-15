"""Score actual operator records; empty input never yields invented time savings."""
import argparse,json,statistics
from pathlib import Path
from research_metrics import score_fields


def grade(record,truth):
    if record.get('completion_status')!='submitted_unscored':raise ValueError('Require an actual completed timer record.')
    if not str(record.get('participant_id','')).strip() or record.get('arm') not in {'manual','assisted'}:raise ValueError('Missing participant assignment.')
    active=float(record['active_seconds']);elapsed=float(record['elapsed_seconds'])
    if not 0<active<=elapsed:raise ValueError('Invalid measured active/elapsed times.')
    _,counts=score_fields(truth['fields'],record['fields'],truth['type'])
    return {'participant_id':record['participant_id'],'case_id':truth['id'],'type':truth['type'],'arm':record['arm'],
        'active_seconds':active,'elapsed_seconds':elapsed,'correct_fields':counts['tp'],'expected_fields':counts['annotated_slots'],
        'route_correct':record['route']==truth['route'],'false_acceptance':truth['route']=='Document Review' and record['route']!='Document Review',
        'fully_correct':counts['tp']==counts['annotated_slots'] and record['route']==truth['route'],
        'corrections_after_import':record.get('corrections_after_import'),'AI_wait_seconds':record.get('AI_wait_seconds'),
        'interruption_seconds':record.get('interruption_seconds'),'workload_rating':record.get('workload_rating')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ground-truth',type=Path,required=True)
    parser.add_argument('--records',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.resolve().relative_to(Path('results').resolve())
    if args.output.exists():raise SystemExit('Use a new output directory.')
    truth={row['id']:row for row in json.loads(args.ground_truth.read_text())}
    scored=[];seen=set()
    for path in sorted(args.records.glob('*.json')):
        record=json.loads(path.read_text());key=(record['participant_id'],record['case_id'])
        if key in seen:raise ValueError('Duplicate participant/case observation; repeated timings are not independent.')
        seen.add(key);scored.append(grade(record,truth[record['case_id']]))
    paired=[]
    for participant in sorted(set(row['participant_id'] for row in scored)):
        manual=[row for row in scored if row['participant_id']==participant and row['arm']=='manual']
        assisted=[row for row in scored if row['participant_id']==participant and row['arm']=='assisted']
        # Only balanced complete four-type blocks enter time-saving comparisons.
        valid=(len(manual)==len(assisted)==4 and {row['type'] for row in manual}=={row['type'] for row in assisted}=={'invoice','purchase_order','receipt','contract'} and all(row['fully_correct'] for row in manual+assisted))
        if valid:
            m=statistics.mean(row['active_seconds'] for row in manual);a=statistics.mean(row['active_seconds'] for row in assisted)
            paired.append({'participant_id':participant,'manual_mean_active_seconds':m,'assisted_mean_active_seconds':a,
                'measured_active_seconds_difference':m-a,'measured_percent_difference':(m-a)/m*100})
    result={'observations':len(scored),'participants':len(set(row['participant_id'] for row in scored)),
        'scored_records':scored,'fully_correct_balanced_participant_comparisons':paired,
        'has_valid_human_baseline':bool(paired),'time_savings_estimate':statistics.mean(row['measured_percent_difference'] for row in paired) if paired else None,
        'limitations':'No data is invented for empty/unbalanced/inaccurate blocks. Report error rates across all observed records, not only complete correct pairs. Participant recruitment, consent, assignment/order, interruptions and human provenance require coordinator verification. No automatic industrial population claim or confidence interval from a handful of operators.'}
    args.output.mkdir(parents=True);(args.output/'human_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'observations':result['observations'],'participants':result['participants'],'has_valid_human_baseline':result['has_valid_human_baseline'],'time_savings_estimate':result['time_savings_estimate']}))


if __name__=='__main__':main()

"""Measured business intelligence with explicit document and batch cohorts."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from statistics import median

from idp.storage.operations import DocumentFilters, OperationsQueries
from idp.utils.money import parse_money


def distribution(values):
    values=sorted(values)
    if not values:
        return {'samples':0,'median_seconds':None,'p95_seconds':None,'min_seconds':None,'max_seconds':None}
    import math
    return {'samples':len(values),'median_seconds':median(values),'p95_seconds':values[max(0,math.ceil(.95*len(values))-1)],'min_seconds':values[0],'max_seconds':values[-1]}


class IntelligenceQueries:
    def __init__(self,repository):
        self.repository=repository

    def report(self,filters=DocumentFilters()):
        where,args=OperationsQueries._where(filters)
        with self.repository.connect() as db:
            rows=db.execute('SELECT d.* FROM documents d'+where+' ORDER BY d.id',args).fetchall()
            runs=db.execute('SELECT r.* FROM processing_runs r JOIN documents d ON d.id=r.document_id'+where,args).fetchall()
            events=db.execute('SELECT e.* FROM review_events e JOIN documents d ON d.id=e.document_id'+where,args).fetchall()
            cases={row['document_id']:dict(row) for row in db.execute('SELECT c.* FROM review_cases c JOIN documents d ON d.id=c.document_id'+where,args)}
            # Batch failures have no document: batch cohort must be independent of document filters.
            clauses=[]; parameters=[]
            if filters.start_date:
                clauses.append('j.created_at>=?'); parameters.append(filters.start_date.isoformat())
            if filters.end_date:
                clauses.append('j.created_at<?'); parameters.append((filters.end_date+timedelta(days=1)).isoformat())
            if filters.batch_id:
                clauses.append('j.id=?'); parameters.append(filters.batch_id)
            batch_where=' WHERE '+' AND '.join(clauses) if clauses else ''
            items=db.execute('SELECT i.* FROM batch_items i JOIN batch_jobs j ON j.id=i.batch_id'+batch_where,parameters).fetchall()
            attempts=db.execute('SELECT a.* FROM batch_attempts a JOIN batch_items i ON i.id=a.item_id JOIN batch_jobs j ON j.id=i.batch_id'+batch_where,parameters).fetchall()
        groups=defaultdict(lambda:[Decimal('0'),0])
        types=Counter(); validation=Counter(); anomalies=Counter(); policies=Counter(); teams=Counter(); age=Counter()
        eligible=escalated=high=0; duplicates=[]; latencies=[]
        now=datetime.now(timezone.utc)
        for row in rows:
            state=json.loads(row['full_result']); fields=state.get('extracted_fields',{})
            types[row['document_type']]+=1
            valid=state.get('validation_passed')
            validation['Passed' if valid is True else 'Failed' if valid is False else 'Unrecorded']+=1
            for error in state.get('validation_errors',[]):
                # Field/error strings are visible explanations, not claimed statistically unique defects.
                validation[error]+=1
            for item in state.get('anomalies',[]):
                anomalies[item.get('code','Unknown')]+=1
            for rule in state.get('policy_failed_rules',[]):
                policies[rule]+=1
            safe=row['workflow_status']=='pending_department_review' and valid is True and not state.get('requires_review') and state.get('risk_level')=='low' and not state.get('cross_document_issues') and row['review_decision'] not in {'rejected','needs_correction','escalated'}
            eligible+=int(safe)
            escalated+=int(row['workflow_status'] in {'manual_review','anomaly_review','unclassified_review'})
            is_high=any(item.get('code')=='LARGE_AMOUNT' for item in state.get('anomalies',[]))
            high+=int(is_high)
            case=cases.get(row['id'],{})
            if case.get('case_status') not in {'approved','rejected'}:
                teams[case.get('team',row['assigned_department'])]+=1
                try:
                    created=datetime.fromisoformat(row['created_at'])
                    days=max(0,(now-created).total_seconds()/86400) if created.tzinfo else None
                except (ValueError,TypeError):
                    days=None
                age['Unknown' if days is None else 'Under 1 day' if days<1 else '1–7 days' if days<=7 else 'Over 7 days']+=1
            identifier={'invoice':'invoice_number','purchase_order':'po_number','receipt':'receipt_number','contract':'contract_number'}.get(row['document_type'])
            if identifier and fields.get(identifier):
                party={'invoice':'seller','purchase_order':'vendor','receipt':'seller','contract':'party_a'}[row['document_type']]
                duplicates.append((row['document_type'],' '.join(str(fields[identifier]).casefold().split()),' '.join(str(fields.get(party) or '').casefold().split())))
            if row['document_type']!='invoice':
                continue
            money=parse_money(fields.get('total'))
            if not money:
                continue
            currency=money.currency or 'Unspecified currency'
            category='Rejected' if row['review_decision']=='rejected' else 'Eligible for departmental processing' if safe else 'Review required'
            for dimension,key in [('currency',category),('supplier',str(fields.get('seller') or 'Unspecified supplier')),
                ('day',row['created_at'][:10]),('po',state.get('cross_document_status','Unrecorded')),
                ('high_value','Above threshold' if is_high else 'Within threshold / not classified')]:
                total=groups[(dimension,currency,key)]; total[0]+=money.amount; total[1]+=1
        for row in runs:
            if row['is_duplicate'] or not row['result_snapshot']:
                continue
            seconds=json.loads(row['result_snapshot']).get('processing_duration_seconds')
            if isinstance(seconds,(int,float)) and seconds>=0:
                latencies.append(seconds)
        corrected={row['document_id'] for row in events if row['event_type']=='correction'}
        intervened={row['document_id'] for row in events if row['actor_kind']=='prototype_operator'}
        duplicate_counts=Counter(duplicates)
        batch_states=Counter(row['state'] for row in items)
        terminal=sum(batch_states[key] for key in ('completed','duplicate','review_required','failed'))
        successful=sum(batch_states[key] for key in ('completed','duplicate','review_required'))
        financial={dimension:[{'currency':currency,'category':key,'invoice_count':count,'extracted_value':format(value,'.2f')} for (group,currency,key),(value,count) in sorted(groups.items()) if group==dimension] for dimension in ('currency','supplier','day','po','high_value')}
        ratio=lambda numerator,denominator: numerator/denominator if denominator else None
        return {'definitions':{
            'document_cohort':'All matching unique current documents received in the selected UTC dates; financial totals use latest extracted fields, once per source hash.',
            'financial':'Nominal extracted invoice values; currencies never summed together; unparseable totals excluded; unspecified currency remains separate. Eligibility and approval are not payment, revenue or execution.',
            'activity':'All recorded runs and review events for the selected document cohort, including later events. Historical pre-migration events and durations remain unavailable.',
            'batch_cohort':'Batches created in selected UTC dates and optional batch ID. Other document filters do not apply because failed/queued items may have no document.',
            'batch_rates':'Successful terminal items / all terminal items; failed terminal items / all terminal items. Successful includes review-required and duplicates, not authorized business outcomes.',
            'latency':'Successful non-cached processing runs with measured end-to-end duration. Batch attempt durations reported separately; nearest-rank p95; no fabricated legacy timings.',
            'review':'Backlog excludes approved/rejected cases; age is time since receipt, not human turnaround. Correction/intervention rates use distinct cohort documents / cohort size.',
            'duplicates':'Upload duplicates are cached submissions. Business duplicate indicators count distinct source records sharing type, normalized identifier and party.'},
            'unique_documents':len(rows),'types':dict(types),'eligible_documents':eligible,'manual_review_documents':escalated,
            'rejected_documents':sum(row['review_decision']=='rejected' for row in rows),
            'financial':financial,'unparseable_invoice_totals':sum(row['document_type']=='invoice' and parse_money(json.loads(row['extracted_data']).get('total')) is None for row in rows),
            'high_value_documents':high,'validation_patterns':dict(validation),'anomaly_patterns':dict(anomalies),'policy_patterns':dict(policies),
            'department_backlog':dict(teams),'backlog_age':dict(age),'corrected_documents':len(corrected),'correction_events':sum(row['event_type']=='correction' for row in events),
            'intervened_documents':len(intervened),'correction_rate':ratio(len(corrected),len(rows)),'intervention_rate':ratio(len(intervened),len(rows)),
            'recorded_submissions':len(runs),'duplicate_submissions':sum(row['is_duplicate'] for row in runs),
            'duplicate_submission_rate':ratio(sum(row['is_duplicate'] for row in runs),len(runs)),
            'duplicate_business_groups':[{'type':key[0],'identifier':key[1],'party':key[2],'documents':count} for key,count in duplicate_counts.items() if count>1],
            'processing_time':distribution(latencies),'batch_attempt_time':distribution([row['duration_seconds'] for row in attempts if row['duration_seconds'] is not None]),
            'batches':{'items':len(items),'states':dict(batch_states),'terminal_items':terminal,'successful_terminal_items':successful,
                'success_rate':ratio(successful,terminal),'failure_rate':ratio(batch_states['failed'],terminal),
                'retried_items':sum(row['attempts']>1 for row in items),'retry_rate':ratio(sum(row['attempts']>1 for row in items),len(items)),
                'attempts':len(attempts),'failed_attempts':sum(row['state']=='failed' for row in attempts)}}

"""Single guarded mutation boundary for human review and team operations."""
import copy
import json
import re
from datetime import datetime, timezone

from idp.agents.validation_agent import ValidationAgent
from idp.agents.anomaly_agent import AnomalyDetectionAgent
from idp.agents.cross_document_agent import CrossDocumentAgent
from idp.agents.routing_agent import WorkflowRoutingAgent
from idp.llm.schemas import AIExtractionResult
from idp.storage.operations import DocumentFilters, OperationsQueries

TEAMS = ('Finance','Procurement','Expense Processing','Legal','Document Review','Risk Review','Document Operations')
EDITABLE = set(AIExtractionResult.model_fields) - {'confidence','field_evidence','contract_parties','unsupported_contract_reasons'}


class ReviewConflict(ValueError):
    pass


class UnsafeApproval(ValueError):
    pass


class ReviewService:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def identity(actor,reason):
        if not str(actor or '').strip() or not str(reason or '').strip():
            raise ValueError('A prototype operator identifier and recorded reason are required.')
        if len(actor)>120 or len(reason)>4000:
            raise ValueError('Operator identifier or reason is too long.')
        if actor.strip().startswith('system:'):
            raise ValueError('The system: prefix is reserved for processing events. Use a prototype operator identifier.')

    @staticmethod
    def validation_summary(state):
        return {key:state.get(key) for key in ('validation_passed','validation_errors','validation_warnings',
            'cross_document_status','cross_document_issues','anomalies','risk_level','requires_review','workflow_status')}

    def validate(self, state):
        result = copy.deepcopy(state)
        previous_issues = result.get('cross_document_issues',[])
        other = [item for item in result.get('anomalies',[]) if item not in previous_issues]
        result.update(ValidationAgent().run(result))
        human_errors=list(result.get('human_evidence_errors',{}).values())
        if human_errors:
            result['validation_warnings'] += human_errors
            result['validation_passed']=False
            result['requires_review']=True
        result.update(AnomalyDetectionAgent().run(result))
        # Derived checks may resolve after correction; independent high-risk flags never silently clear.
        for item in other:
            if item.get('severity')=='high' and item not in result['anomalies']:
                result['anomalies'].append(item)
        if state.get('risk_level')=='high' or any(item.get('severity')=='high' for item in result['anomalies']):
            result['risk_level']='high'
        result.update(CrossDocumentAgent(self.repository).run(result))
        linked_id=result.get('matched_document_id')
        if linked_id and result.get('cross_document_status')=='matched':
            linked=self.repository.get_document(linked_id)
            po=linked['full_result'] if linked else {}
            if not linked or linked['review_decision'] in {'rejected','needs_correction','escalated'} or not po.get('validation_passed') or po.get('requires_review') or po.get('risk_level')!='low':
                issue={'code':'PO_REVIEW_BLOCK','severity':'medium','description':'The referenced PO is rejected or requires validation/review. Escalate or resolve the PO before invoice approval.'}
                result.update(cross_document_status='incomplete',requires_review=True,risk_level='high' if result.get('risk_level')=='high' else 'medium')
                result['cross_document_issues'].append(issue)
                result['anomalies'].append(issue)
        result.update(WorkflowRoutingAgent().run(result))
        return result

    def preview_correction(self, document_id, changes, evidence):
        document = self.repository.get_document(document_id)
        if not document:
            raise ValueError('Document is no longer available.')
        if any(key not in EDITABLE for key in changes):
            raise ValueError('Only supported extracted fields can be corrected.')
        if any(value is not None and (not isinstance(value,str) or len(value)>2000) for value in changes.values()):
            raise ValueError('Corrections must be short text values or empty.')
        if any(not isinstance(value,str) or len(value)>4000 for value in evidence.values()):
            raise ValueError('Evidence quotes must be short text.')
        state = copy.deepcopy(document['full_result'])
        fields = state.setdefault('extracted_fields',{})
        quotes = state.setdefault('field_evidence',{})
        changed = []
        human_errors=state.setdefault('human_evidence_errors',{})
        for key,value in changes.items():
            value = value.strip() if isinstance(value,str) else None
            value = value or None
            if value != fields.get(key) or key in evidence and evidence[key]!=(quotes.get(key) or ''):
                previous_value=fields.get(key)
                fields[key]=value
                quotes[key]=evidence.get(key,'')
                changed.append(key)
                human_errors.pop(key,None)
                if value and ValidationAgent.normalize_text(value) not in ValidationAgent.normalize_text(quotes[key]):
                    human_errors[key]=f'Correction evidence does not contain the corrected value: {key}'
                if key=='po_reference' and previous_value and not value:
                    human_errors[key]='A known PO reference cannot be removed to bypass reconciliation: po_reference. Escalate for source verification.'
        # Remove only extraction warnings attributable to fields actually revalidated.
        # ValidationAgent independently checks every current value and quote against original OCR.
        if changed:
            state['evidence_warnings'] = [warning for warning in state.get('evidence_warnings',[]) if not any(re.search(r'\b'+re.escape(key)+r'\b',warning) for key in changed)]
            state['fallback_used'] = [key for key in state.get('fallback_used',[]) if key not in changed]
        if state.get('document_type')=='contract' and {'party_a','party_b'} & set(changed):
            state['contract_parties'] = [fields[key] for key in ('party_a','party_b') if fields.get(key)]
        result = self.validate(state)
        return {'revision':document['revision'],'processing_version_id':document['processing_version_id'],'state':result,'changed_fields':changed}

    @staticmethod
    def _current(db, document_id, expected_revision):
        row = db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        if not row:
            raise ValueError('Document is no longer available.')
        if expected_revision is None or row['revision']!=expected_revision:
            raise ReviewConflict('This document changed. Refresh and inspect the latest version before saving.')
        return dict(row)

    def event(self, db, document, event_type, previous, new, actor, reason, notes='',decision=None,state=None):
        updated = db.execute('SELECT revision FROM documents WHERE id=?',(document['id'],)).fetchone()[0]
        return db.execute('''INSERT INTO review_events(document_id,processing_version_id,event_type,previous_values,new_values,
            actor,actor_kind,created_at,decision,reason,notes,validation_results,rule_versions,previous_revision,new_revision)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (document['id'],document['processing_version_id'],event_type,json.dumps(previous,ensure_ascii=False),json.dumps(new,ensure_ascii=False),
             actor.strip(),'system' if actor.startswith('system:') else 'prototype_operator',self.repository.timestamp(),decision,reason.strip(),notes[:8000],
             json.dumps(self.validation_summary(state or json.loads(document['full_result']))),None,document['revision'],updated)).lastrowid

    def apply_correction(self, document_id, expected_revision, changes, evidence, *, actor, reason, notes=''):
        self.identity(actor,reason)
        preview = self.preview_correction(document_id,changes,evidence)
        if preview['revision']!=expected_revision:
            raise ReviewConflict('This correction preview is stale. Refresh before saving.')
        if not preview['changed_fields']:
            raise ValueError('No field or evidence changes were provided.')
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            document = self._current(db,document_id,expected_revision)
            state = self.validate(preview['state'])
            provenance = state.setdefault('field_provenance',{})
            for key in preview['changed_fields']:
                provenance[key]={'source':'human_correction','prototype_operator':actor.strip(),
                    'recorded_at':self.repository.timestamp(),'processing_version_id':document['processing_version_id']}
            original = json.loads(document['full_result'])
            db.execute('''UPDATE documents SET full_result=?,extracted_data=?,workflow_status=?,assigned_department=?,
                review_decision='pending',review_notes=NULL,updated_at=? WHERE id=?''',
                (json.dumps(state,ensure_ascii=False),json.dumps(state['extracted_fields'],ensure_ascii=False),state['workflow_status'],state['assigned_department'],self.repository.timestamp(),document_id))
            db.execute("UPDATE review_cases SET case_status='in_review',updated_at=? WHERE document_id=?",(self.repository.timestamp(),document_id))
            event_id = self.event(db,document,'correction',{'fields':original.get('extracted_fields',{}),'evidence':original.get('field_evidence',{})},
                {'fields':state['extracted_fields'],'evidence':state.get('field_evidence',{}),'provenance':provenance},actor,reason,notes,state=state)
            if document['document_type']=='purchase_order':
                self.invalidate_dependents(db,document_id,'Referenced PO fields were corrected; fresh invoice review is required.')
        return event_id

    def decide(self, document_id, expected_revision, decision, *, actor, reason, notes=''):
        self.identity(actor,reason)
        if decision not in {'approved','rejected','needs_correction','escalated'}:
            raise ValueError('Unsupported review decision.')
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            document = self._current(db,document_id,expected_revision)
            state = self.validate(json.loads(document['full_result']))
            if decision=='approved' and (not state.get('validation_passed') or state.get('requires_review')
                or state.get('risk_level')!='low' or state.get('cross_document_issues')
                or state.get('cross_document_status') in {'unmatched','ambiguous','mismatch','incomplete'}):
                raise UnsafeApproval('Approval blocked: resolve mandatory fields, evidence, PO and risk issues or escalate the case.')
            if decision in {'needs_correction','escalated'}:
                state.update(workflow_status='manual_review',assigned_department='Document Review',requires_review=True,
                    routing_reason='Human requested correction or escalation; departmental processing is blocked.')
            if decision=='rejected':
                state.update(workflow_status='rejected',requires_review=True,routing_reason='Human review rejected this document; no business transaction is executed.')
            db.execute('''UPDATE documents SET review_decision=?,review_notes=?,full_result=?,workflow_status=?,assigned_department=?,updated_at=? WHERE id=?''',
                (decision,notes.strip() or reason.strip(),json.dumps(state,ensure_ascii=False),state['workflow_status'],state['assigned_department'],self.repository.timestamp(),document_id))
            status = {'approved':'approved','rejected':'rejected','needs_correction':'awaiting_correction','escalated':'escalated'}[decision]
            db.execute('UPDATE review_cases SET case_status=?,updated_at=? WHERE document_id=?',(status,self.repository.timestamp(),document_id))
            event_id=self.event(db,document,'decision',{'decision':document['review_decision'],'workflow_status':document['workflow_status']},
                {'decision':decision,'workflow_status':state['workflow_status']},actor,reason,notes,decision,state)
            if document['document_type']=='purchase_order' and decision!='approved':
                self.invalidate_dependents(db,document_id,'Referenced PO was rejected, escalated or sent for correction.')
            return event_id

    def invalidate_dependents(self,db,po_id,reason):
        rows=db.execute("SELECT * FROM documents WHERE document_type='invoice' AND json_extract(full_result,'$.matched_document_id')=? AND review_decision!='rejected'",(po_id,)).fetchall()
        for row in rows:
            document=dict(row)
            state=json.loads(document['full_result'])
            issue={'code':'PO_CHANGED','severity':'medium','description':reason}
            state['cross_document_issues']=[issue]
            state.setdefault('anomalies',[]).append(issue)
            state.update(cross_document_status='incomplete',requires_review=True,risk_level='high' if state.get('risk_level')=='high' else 'medium',workflow_status='manual_review',assigned_department='Document Review',routing_reason=reason)
            decision=document['review_decision'] if document['review_decision'] in {'needs_correction','escalated'} else 'needs_correction'
            db.execute('UPDATE documents SET full_result=?,workflow_status=?,assigned_department=?,review_decision=?,updated_at=? WHERE id=?',
                (json.dumps(state,ensure_ascii=False),state['workflow_status'],state['assigned_department'],decision,self.repository.timestamp(),document['id']))
            db.execute("UPDATE review_cases SET case_status=CASE WHEN case_status='escalated' THEN case_status ELSE 'awaiting_correction' END,updated_at=? WHERE document_id=?",(self.repository.timestamp(),document['id']))
            self.event(db,document,'po_dependency_change',{'decision':document['review_decision'],'cross_document_status':json.loads(document['full_result']).get('cross_document_status')},
                {'decision':decision,'cross_document_status':'incomplete'},'system:review-dependency',reason,decision=decision,state=state)

    def manage(self, document_id, expected_revision, action, *, actor, reason, team=None, assignee=None, status=None, priority=None):
        self.identity(actor,reason)
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            document = self._current(db,document_id,expected_revision)
            case = dict(db.execute('SELECT * FROM review_cases WHERE document_id=?',(document_id,)).fetchone())
            previous = dict(case)
            if action=='claim':
                if case['case_status'] in {'approved','rejected'}:
                    raise ValueError('A completed case cannot be reopened by claiming it. Use an explicit correction or review decision.')
                if case['assignee'] and case['assignee']!=actor.strip():
                    raise ReviewConflict('This case is already claimed. Use explicit reassignment with a reason.')
                case.update(assignee=actor.strip(),case_status=case['case_status'] if case['case_status'] in {'awaiting_correction','escalated'} else 'in_review')
            elif action=='assign':
                if team not in TEAMS or len(str(assignee or ''))>120:
                    raise ValueError('Select a supported team and a short operator identifier.')
                case.update(team=team,assignee=str(assignee or '').strip() or None)
            elif action=='status':
                if status not in {'open','in_review','on_hold'} or case['case_status'] in {'approved','rejected','awaiting_correction','escalated'}:
                    raise ValueError('Use a review decision to change a terminal or escalated case; status updates cannot approve or close it.')
                case['case_status']=status
            elif action=='priority':
                if priority not in {'normal','high','urgent'}:
                    raise ValueError('Unsupported priority.')
                case['priority']=priority
            else:
                raise ValueError('Unsupported case action.')
            case['updated_at']=self.repository.timestamp()
            db.execute('UPDATE review_cases SET team=?,assignee=?,case_status=?,priority=?,updated_at=? WHERE document_id=?',
                (case['team'],case['assignee'],case['case_status'],case['priority'],case['updated_at'],document_id))
            # Assignment is a separate operational team, never a change of validated routing.
            db.execute('UPDATE documents SET revision=revision+1 WHERE id=?',(document_id,))
            return self.event(db,document,action,previous,case,actor,reason)

    def history(self, document_id):
        with self.repository.connect() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM review_events WHERE document_id=? ORDER BY id DESC',(document_id,))]
        for row in rows:
            for key in ('previous_values','new_values','validation_results','rule_versions'):
                row[key]=json.loads(row[key]) if row[key] else None
        return rows

    def case(self, document_id):
        with self.repository.connect() as db:
            row = db.execute('SELECT * FROM review_cases WHERE document_id=?',(document_id,)).fetchone()
        return dict(row) if row else None

    def queue(self, filters=DocumentFilters(), *, team='', risk='', case_status='', assignee='', page=1, include_closed=False):
        where, parameters = OperationsQueries._where(filters)
        extra=[]
        if not include_closed and case_status not in {'approved','rejected'}:
            extra.append("c.case_status NOT IN ('approved','rejected')")
        if team:
            if team=='Procurement':
                extra.append("(c.team=? OR (d.document_type='invoice' AND json_extract(d.full_result,'$.cross_document_status') IN ('unmatched','ambiguous','mismatch','incomplete')))")
            else:
                extra.append('c.team=?')
            parameters.append(team)
        for column,value in (("json_extract(d.full_result,'$.risk_level')",risk),('c.case_status',case_status),('c.assignee',assignee)):
            if value:
                extra.append(column+'=?')
                parameters.append(value)
        if extra:
            where += (' AND ' if where else ' WHERE ')+' AND '.join(extra)
        query = ' FROM documents d JOIN review_cases c ON c.document_id=d.id'
        with self.repository.connect() as db:
            total = db.execute('SELECT count(*)'+query+where,parameters).fetchone()[0]
            rows=[dict(row) for row in db.execute('''SELECT d.id,d.filename,d.document_type,d.workflow_status,d.review_decision,
                d.created_at,d.revision,c.team,c.assignee,c.case_status,c.priority,json_extract(d.full_result,'$.risk_level') AS risk,
                json_extract(d.full_result,'$.cross_document_status') AS po_status'''+query+where+'''
                ORDER BY CASE c.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                CASE json_extract(d.full_result,'$.risk_level') WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                d.created_at,d.id LIMIT 20 OFFSET ?''',[*parameters,(max(1,page)-1)*20])]
        now = datetime.now(timezone.utc)
        for row in rows:
            try:
                created = datetime.fromisoformat(row['created_at'])
                row['age_days']=max(0,(now-created).total_seconds()/86400) if created.tzinfo else None
            except (ValueError,TypeError):
                row['age_days']=None
        return rows,total

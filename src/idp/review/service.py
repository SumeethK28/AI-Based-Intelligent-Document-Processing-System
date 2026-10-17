"""Single guarded mutation boundary for human review and team operations."""
import copy
import json
import re
from idp.security.auth import AccessDenied, digest
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
            'cross_document_status','cross_document_issues','anomalies','risk_level','requires_review','workflow_status',
            'policy_version_id','rule_outcomes','policy_failed_rules','policy_latency_ms','policy_evaluation_error')}

    def validate(self, state):
        checks_repository=self.repository
        if not self.repository.internal:
            self.repository.access.document(state.get('document_id'),'review',mutation=True)
            from idp.security import INTERNAL
            from idp.storage.repository import DocumentRepository
            checks_repository=DocumentRepository(self.repository.db_path,_capability=INTERNAL)
            original=checks_repository.get_document(state['document_id'])['full_result']
            if state.get('ocr_text')!=original.get('ocr_text'):
                from idp.security.auth import AccessDenied
                raise AccessDenied('Original OCR evidence cannot be supplied or changed by a caller.')
            if self.repository.access.principal()['role']!='Administrator' and state.get('policy_version_id')!=original.get('policy_version_id'):
                from idp.security.auth import AccessDenied
                raise AccessDenied('Only explicit administrator reevaluation may change the recorded policy.')
        from idp.policy.service import PolicyService
        policy = PolicyService(checks_repository)
        try:
            result = policy.bind(state)
        except Exception:
            from idp.policy.schema import DEFAULT
            result = copy.deepcopy(state)
            result.update(policy_config=copy.deepcopy(DEFAULT),policy_evaluation_error='Policy binding failed.')
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
        if not self.repository.internal and self.repository.access.principal()['role']!='Administrator' and not result.get('validation_passed'):
            issue={'code':'INCOMPLETE_COMPARISON','severity':'medium','description':'Verify this document and its original evidence before purchase-order comparison. No unrelated PO information is disclosed.'}
            result.update(cross_document_status='incomplete' if result.get('extracted_fields',{}).get('po_reference') else 'not_checked',
                cross_document_issues=[issue] if result.get('extracted_fields',{}).get('po_reference') else [],matched_document_id=None)
        else:
            result.update(CrossDocumentAgent(checks_repository).run(result))
        linked_id=result.get('matched_document_id')
        if linked_id and result.get('cross_document_status')=='matched':
            linked=checks_repository.get_document(linked_id)
            po=linked['full_result'] if linked else {}
            if not linked or linked['review_decision'] in {'rejected','needs_correction','escalated'} or not po.get('validation_passed') or po.get('requires_review') or po.get('risk_level')!='low':
                issue={'code':'PO_REVIEW_BLOCK','severity':'medium','description':'The referenced PO is rejected or requires validation/review. Escalate or resolve the PO before invoice approval.'}
                result.update(cross_document_status='incomplete',requires_review=True,risk_level='high' if result.get('risk_level')=='high' else 'medium')
                result['cross_document_issues'].append(issue)
                result['anomalies'].append(issue)
        result = policy.evaluate(result)
        result.update(WorkflowRoutingAgent().run(result))
        return result

    def preview_correction(self, document_id, changes, evidence):
        self.repository.access.actor(None,'review',document_id)
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
        state['document_id'] = document_id
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

    def _current(self, db, document_id, expected_revision):
        if not self.repository.internal:
            self.repository.access.document(document_id,'review',mutation=True)
        row = db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
        if not row:
            raise ValueError('Document is no longer available.')
        if expected_revision is None or row['revision']!=expected_revision:
            raise ReviewConflict('This document changed. Refresh and inspect the latest version before saving.')
        return dict(row)

    def event(self, db, document, event_type, previous, new, actor, reason, notes='',decision=None,state=None):
        if not self.repository.internal:
            principal=self.repository.require('account')
            new={**new,'actor_context':{key:principal[key] for key in ('id','username','role','departments')}}
        updated = db.execute('SELECT revision FROM documents WHERE id=?',(document['id'],)).fetchone()[0]
        event_id = db.execute('''INSERT INTO review_events(document_id,processing_version_id,event_type,previous_values,new_values,
            actor,actor_kind,created_at,decision,reason,notes,validation_results,rule_versions,previous_revision,new_revision)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (document['id'],document['processing_version_id'],event_type,json.dumps(previous,ensure_ascii=False),json.dumps(new,ensure_ascii=False),
             actor.strip(),'system' if actor.startswith('system:') else 'prototype_operator' if self.repository.internal else 'authenticated_user',self.repository.timestamp(),decision,reason.strip(),notes[:8000],
             json.dumps(self.validation_summary(state or json.loads(document['full_result']))),
             json.dumps({'policy_version_id':(state or json.loads(document['full_result'])).get('policy_version_id')}),document['revision'],updated)).lastrowid
        self.repository.access.attribution(db,'review_events',event_id)
        return event_id

    def apply_correction(self, document_id, expected_revision, changes, evidence, *, actor, reason, notes=''):
        actor=self.repository.access.actor(actor,'review',document_id)
        self.identity(actor,reason)
        preview = self.preview_correction(document_id,changes,evidence)
        if preview['revision']!=expected_revision:
            raise ReviewConflict('This correction preview is stale. Refresh before saving.')
        if not preview['changed_fields']:
            raise ValueError('No field or evidence changes were provided.')
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            document = self._current(db,document_id,expected_revision)
            state = self.validate(preview['state'])
            provenance = state.setdefault('field_provenance',{})
            for key in preview['changed_fields']:
                provenance[key]={'source':'human_correction','prototype_operator':actor.strip(),
                    'recorded_at':self.repository.timestamp(),'processing_version_id':document['processing_version_id']}
                if not self.repository.internal:
                    provenance[key].update(actor_kind='authenticated_user',actor_user_id=self.repository.access.principal()['id'])
            original = json.loads(document['full_result'])
            db.execute('''UPDATE documents SET full_result=?,extracted_data=?,workflow_status=?,assigned_department=?,
                review_decision='pending',review_notes=NULL,updated_at=? WHERE id=?''',
                (json.dumps(state,ensure_ascii=False),json.dumps(state['extracted_fields'],ensure_ascii=False),state['workflow_status'],state['assigned_department'],self.repository.timestamp(),document_id))
            case=db.execute('SELECT team FROM review_cases WHERE document_id=?',(document_id,)).fetchone()
            returned_to=state['assigned_department'] if case['team']=='Document Review' and state['workflow_status']=='pending_department_review' else None
            if returned_to:
                db.execute("UPDATE review_cases SET team=?,assignee=NULL,case_status='open',updated_at=? WHERE document_id=?",(returned_to,self.repository.timestamp(),document_id))
            else:
                db.execute("UPDATE review_cases SET case_status='in_review',updated_at=? WHERE document_id=?",(self.repository.timestamp(),document_id))
            event_id = self.event(db,document,'correction',{'fields':original.get('extracted_fields',{}),'evidence':original.get('field_evidence',{}),'team':case['team']},
                {'fields':state['extracted_fields'],'evidence':state.get('field_evidence',{}),'provenance':provenance,'team':returned_to or case['team']},actor,reason,notes,state=state)
            if document['document_type']=='purchase_order':
                self.invalidate_dependents(db,document_id,'Referenced PO fields were corrected; fresh invoice review is required.')
        return event_id

    def decide(self, document_id, expected_revision, decision, *, actor, reason, notes=''):
        actor=self.repository.access.actor(actor,'review',document_id)
        self.identity(actor,reason)
        if decision not in {'approved','rejected','needs_correction','escalated'}:
            raise ValueError('Unsupported review decision.')
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            document = self._current(db,document_id,expected_revision)
            state = json.loads(document['full_result'])
            state['document_id'] = document_id
            state = self.validate(state)
            if decision=='approved' and (not state.get('validation_passed') or state.get('requires_review')
                or state.get('risk_level')!='low' or state.get('cross_document_issues')
                or state.get('cross_document_status') in {'unmatched','ambiguous','mismatch','incomplete'}):
                if not self.repository.internal:
                    from idp.security.auth import AuthService
                    AuthService(self.repository).event('blocked_review_approval','denied','review',self.repository.access.principal()['id'])
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

    @staticmethod
    def handoff_departments(state,kind,current_team):
        destination={'invoice':'Finance','purchase_order':'Procurement','receipt':'Expense Processing','contract':'Legal'}.get(kind)
        choices={'Document Review'}
        if state.get('workflow_status')=='pending_department_review' and destination: choices.add(destination)
        if kind=='invoice' and current_team=='Procurement': choices.add('Finance')
        if kind=='invoice' and state.get('cross_document_status') in {'unmatched','ambiguous','mismatch','incomplete'}:
            choices.add('Procurement')
        return sorted(choices-{current_team})

    def manage(self, document_id, expected_revision, action, *, actor, reason, team=None, assignee=None, status=None, priority=None):
        actor=self.repository.access.actor(actor,'assign' if action=='assign' else 'review',document_id)
        if action=='assign' and not self.repository.internal and assignee:
            with self.repository._connect() as db:
                accounts=db.execute('SELECT id,username,role,departments FROM users WHERE active=1').fetchall()
            valid=any(assignee==f"user:{row['id']}:{row['username']}" and (row['role']=='Administrator' or team in json.loads(row['departments']) and row['role'].endswith('Reviewer')) for row in accounts)
            if not valid: raise ValueError('Assign only to an active authenticated reviewer authorized for that team.')
        self.identity(actor,reason)
        with self.repository._connect() as db:
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
            elif action=='handoff':
                state=json.loads(document['full_result'])
                permitted=self.handoff_departments(state,document['document_type'],case['team'])
                if team not in permitted or team==case['team'] or case['case_status'] in {'approved','rejected'}:
                    raise ValueError('Select a responsible department for this unresolved or corrected case.')
                destination={'invoice':'Finance','purchase_order':'Procurement','receipt':'Expense Processing','contract':'Legal'}.get(document['document_type'])
                if team==destination:
                    state['document_id']=document_id
                    state=self.validate(state)
                    if state.get('workflow_status')!='pending_department_review' or state.get('risk_level')!='low':
                        raise UnsafeApproval('Return blocked: resolve validation, evidence, reconciliation and risk issues first.')
                    db.execute("UPDATE documents SET full_result=?,extracted_data=?,workflow_status=?,assigned_department=?,review_decision='pending',updated_at=? WHERE id=?",(json.dumps(state,ensure_ascii=False),json.dumps(state.get('extracted_fields',{}),ensure_ascii=False),state['workflow_status'],state['assigned_department'],self.repository.timestamp(),document_id))
                case.update(team=team,assignee=None,case_status='open')
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
            return self.event(db,document,action,previous,case,actor,reason,state=state if action=='handoff' else None)

    def history(self, document_id):
        self.repository.access.document(document_id)
        with self.repository._connect() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM review_events WHERE document_id=? ORDER BY id DESC',(document_id,))]
        for row in rows:
            for key in ('previous_values','new_values','validation_results','rule_versions'):
                row[key]=json.loads(row[key]) if row[key] else None
        return rows

    def case(self, document_id):
        self.repository.access.document(document_id)
        with self.repository._connect() as db:
            row = db.execute('SELECT * FROM review_cases WHERE document_id=?',(document_id,)).fetchone()
        return dict(row) if row else None

    def queue(self, filters=DocumentFilters(), *, team='', risk='', case_status='', assignee='', page=1, include_closed=False, view='department'):
        where, parameters = OperationsQueries._where(filters)
        from idp.security.access import scoped_where
        where,parameters=scoped_where(self.repository,where,parameters,'review')
        extra=[]
        if view not in {'department','mine','unclaimed'}: raise ValueError('Unsupported work view.')
        if view=='mine':
            principal=self.repository.require('review')
            extra.append('c.assignee=?')
            parameters.append(f"user:{principal['id']}:{principal['username']}")
        elif view=='unclaimed': extra.append("coalesce(c.assignee,'')=''")
        if not include_closed and case_status not in {'approved','rejected'}:
            extra.append("c.case_status NOT IN ('approved','rejected')")
        if team:
            extra.append('c.team=?')
            parameters.append(team)
        for column,value in (("json_extract(d.full_result,'$.risk_level')",risk),('c.case_status',case_status),('c.assignee',assignee)):
            if value:
                extra.append(column+'=?')
                parameters.append(value)
        if extra:
            where += (' AND ' if where else ' WHERE ')+' AND '.join(extra)
        query = ' FROM documents d JOIN review_cases c ON c.document_id=d.id'
        with self.repository._connect() as db:
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

    def collaboration(self, document_id):
        """Authorized context; references confer no decision-making permission."""
        document=self.repository.get_document(document_id)
        case=self.case(document_id)
        state=document['full_result']
        try:
            self.repository.access.actor(None,'review',document_id)
            can_review=True
        except AccessDenied:
            can_review=False
        with self.repository._connect() as db:
            origin=db.execute('SELECT original_state FROM processing_versions WHERE document_id=? ORDER BY id LIMIT 1',(document_id,)).fetchone()
            upload=db.execute('SELECT actor_context,processed_at FROM processing_runs WHERE document_id=? AND actor_context IS NOT NULL ORDER BY id LIMIT 1',(document_id,)).fetchone()
            submitted=db.execute('SELECT b.actor_context,b.created_at FROM batch_jobs b JOIN batch_items i ON i.batch_id=b.id WHERE i.document_id=? AND b.actor_context IS NOT NULL ORDER BY b.created_at,i.id LIMIT 1',(document_id,)).fetchone()
            candidates=db.execute("SELECT id FROM documents WHERE id=? OR (document_type='invoice' AND json_extract(full_result,'$.matched_document_id')=?)",(state.get('matched_document_id'),document_id)).fetchall()
        related=[]
        for row in candidates:
            try: linked=self.repository.get_document(row['id'])
            except AccessDenied: continue
            if linked:
                related_case=self.case(linked['id'])
                related.append({'id':linked['id'],'filename':linked['filename'],'document_type':linked['document_type'],
                    'team':related_case['team'],'assignee':related_case['assignee'],'case_status':related_case['case_status'],
                    'review_decision':linked['review_decision'],'last_updated':related_case['updated_at'],'read_only_reference':True})
        return {'can_review':can_review,'original_department':json.loads(origin['original_state']).get('assigned_department') if origin else None,
            'uploaded_by':json.loads(submitted['actor_context']) if submitted else None,'uploaded_at':submitted['created_at'] if submitted else None,
            'processed_by':json.loads(upload['actor_context']) if upload else None,'processed_at':upload['processed_at'] if upload else None,
            'current_department':case['team'],'assigned_reviewer':case['assignee'],'last_updated':max(document['updated_at'],case['updated_at']),
            'related_documents':related,'handoff_departments':self.handoff_departments(state,document['document_type'],case['team']) if can_review else []}

    def related_work(self, filters=DocumentFilters(), *, page=1):
        self.repository.require('review')
        where,args=OperationsQueries(self.repository)._scoped(filters)
        own,own_args=self.repository.access.scope(mutation=True)
        where+=' AND NOT ('+own+')'
        args.extend(own_args)
        query=' FROM documents d JOIN review_cases c ON c.document_id=d.id'+where
        with self.repository._connect() as db:
            total=db.execute('SELECT count(*)'+query,args).fetchone()[0]
            rows=[dict(row) for row in db.execute('SELECT d.id,d.filename,d.document_type,d.workflow_status,d.review_decision,c.team,c.assignee,c.case_status,c.updated_at'+query+' ORDER BY c.updated_at DESC,d.id DESC LIMIT 20 OFFSET ?',[*args,(max(1,page)-1)*20])]
        return rows,total

    def work_summary(self, filters=DocumentFilters()):
        principal=self.repository.require('review')
        where,args=OperationsQueries._where(filters)
        from idp.security.access import scoped_where
        where,args=scoped_where(self.repository,where,args,'review')
        actor=f"user:{principal['id']}:{principal['username']}"
        with self.repository._connect() as db:
            summary=dict(db.execute("SELECT count(*) AS department_cases,coalesce(sum(c.assignee=?),0) AS assigned_to_me,coalesce(sum(coalesce(c.assignee,'')=''),0) AS unclaimed,coalesce(sum(json_extract(d.full_result,'$.cross_document_status') IN ('mismatch','incomplete','unmatched','ambiguous')),0) AS reconciliation_issues FROM documents d JOIN review_cases c ON c.document_id=d.id"+where+(" AND " if where else " WHERE ")+"c.case_status NOT IN ('approved','rejected')",[actor,*args]).fetchone())
            summary['recent_decisions']=[dict(row) for row in db.execute("SELECT e.document_id,d.filename,e.actor,e.decision,e.created_at FROM review_events e JOIN documents d ON d.id=e.document_id"+where+(" AND " if where else " WHERE ")+"e.event_type='decision' ORDER BY e.id DESC LIMIT 5",args)]
        previous=None
        if self.repository.session_token:
            with self.repository._connect() as db:
                previous=db.execute('SELECT max(created_at) FROM auth_sessions WHERE user_id=? AND created_at<(SELECT created_at FROM auth_sessions WHERE token_hash=?)',(principal['id'],digest(self.repository.session_token))).fetchone()[0]
        summary['previous_sign_in']=datetime.fromtimestamp(previous,timezone.utc).isoformat() if previous else None
        summary['recent_changes']=[]
        if previous:
            scope,params=self.repository.access.scope()
            with self.repository._connect() as db:
                summary['recent_changes']=[dict(row) for row in db.execute('SELECT d.id,d.filename,c.team,c.assignee,c.case_status,c.updated_at FROM documents d JOIN review_cases c ON c.document_id=d.id WHERE '+scope+' AND c.updated_at>? ORDER BY c.updated_at DESC LIMIT 5',[*params,summary['previous_sign_in']])]
        return summary

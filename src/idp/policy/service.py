"""Policy lifecycle, explainable evaluation and revision-bound reevaluation."""
import copy
import hashlib
import json
from time import perf_counter

from idp.policy.schema import DEFAULT, validate_config


class PolicyService:
    def __init__(self,repository):
        self.repository=repository

    def active(self):
        self.repository.require('account')
        with self.repository._connect() as db:
            row=dict(db.execute('SELECT * FROM policy_active WHERE singleton=1').fetchone())
        return {**self.version(row['version_id']),'generation':row['generation']}

    def version(self,version_id):
        self.repository.require('account')
        with self.repository._connect() as db:
            row=db.execute('SELECT * FROM policy_versions WHERE id=?',(version_id,)).fetchone()
        if not row:
            raise ValueError('Policy version is unavailable. Processing must remain in review.')
        result=dict(row)
        result['config']=validate_config(json.loads(result['config']))
        return result

    def bind(self,state,version_id=None):
        result=copy.deepcopy(state)
        # Legacy results keep baseline semantics during ordinary review, not today's active policy.
        version_id=version_id if version_id is not None else state.get('policy_version_id')
        policy=self.version(version_id) if version_id is not None else {'id':None,'config':copy.deepcopy(DEFAULT)}
        result.update(policy_version_id=policy['id'],policy_config=policy['config'],policy_evaluation_error=None)
        return result

    def draft(self,config,*,actor,reason):
        actor=self.repository.access.actor(actor,'policy')
        from idp.review.service import ReviewService
        ReviewService.identity(actor,reason)
        validated=validate_config(config)
        with self.repository._connect() as db:
            version = db.execute('INSERT INTO policy_versions(config,actor,reason,created_at) VALUES(?,?,?,?)',
                (json.dumps(validated,sort_keys=True),actor.strip(),reason.strip(),self.repository.timestamp())).lastrowid
            self.repository.access.attribution(db,'policy_versions',version)
            from idp.security.auth import AuthService
            if not self.repository.internal: AuthService(self.repository).event('policy_draft','allowed',str(version),self.repository.access.principal()['id'],db)
            return version

    @staticmethod
    def fingerprint(db):
        # Include PO/current review changes, new documents and policy changes in preview freshness.
        records=[tuple(row) for row in db.execute('SELECT id,revision,full_result FROM documents ORDER BY id')]
        return hashlib.sha256(json.dumps(records,ensure_ascii=False).encode()).hexdigest()

    def preview(self,version_id,document_ids=None):
        self.repository.require('policy')
        from idp.review.service import ReviewService
        self.version(version_id)
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active=dict(db.execute('SELECT * FROM policy_active').fetchone())
            fingerprint=self.fingerprint(db)
            rows=db.execute('SELECT id,full_result,workflow_status,review_decision FROM documents ORDER BY id').fetchall()
            if len(rows)>1000:
                raise ValueError('Full activation preview is limited to 1,000 stored documents in this local prototype.')
            if not rows:
                raise ValueError('Process test documents before previewing and activating a policy.')
            results=[]
            for row in rows:
                if document_ids is not None and row['id'] not in document_ids:
                    continue
                state=self.bind(json.loads(row['full_result']),version_id)
                state['document_id']=row['id']
                after=ReviewService(self.repository).validate(state)
                results.append({'document_id':row['id'],'prior_workflow':row['workflow_status'],
                    'proposed_workflow':after['workflow_status'],'review_decision':row['review_decision'],
                    'department':after['assigned_department'],'rule_outcomes':after['rule_outcomes'],
                    'policy_version_id':version_id,'policy_latency_ms':after['policy_latency_ms']})
            # Subset previews are exploratory and cannot authorize activation.
            complete=document_ids is None
            preview_id=db.execute('INSERT INTO policy_previews(version_id,generation,fingerprint,results,created_at) VALUES(?,?,?,?,?)',
                (version_id,active['generation'],fingerprint,json.dumps({'complete':complete,'documents':results}),self.repository.timestamp())).lastrowid
        return {'id':preview_id,'version_id':version_id,'generation':active['generation'],'complete':complete,'documents':results}

    def activate(self,version_id,preview_id,*,actor,reason,confirmed=False):
        actor=self.repository.access.actor(actor,'policy')
        from idp.review.service import ReviewService, ReviewConflict
        ReviewService.identity(actor,reason)
        if confirmed is not True:
            raise ValueError('Explicit activation confirmation is required.')
        self.version(version_id)
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active=dict(db.execute('SELECT * FROM policy_active').fetchone())
            preview=db.execute('SELECT * FROM policy_previews WHERE id=?',(preview_id,)).fetchone()
            if not preview or preview['version_id']!=version_id or not json.loads(preview['results'])['complete'] or preview['generation']!=active['generation'] or preview['fingerprint']!=self.fingerprint(db):
                raise ReviewConflict('Policy preview is missing or stale. Preview all current documents again before activation.')
            generation=active['generation']+1
            db.execute('UPDATE policy_active SET version_id=?,generation=? WHERE singleton=1',(version_id,generation))
            event=db.execute('INSERT INTO policy_activations(version_id,previous_version_id,preview_id,actor,reason,created_at,generation) VALUES(?,?,?,?,?,?,?)',
                (version_id,active['version_id'],preview_id,actor.strip(),reason.strip(),self.repository.timestamp(),generation))
            self.repository.access.attribution(db,'policy_activations',event.lastrowid)
            from idp.security.auth import AuthService
            if not self.repository.internal: AuthService(self.repository).event('policy_activation','allowed',str(version_id),self.repository.access.principal()['id'],db)
        return generation

    def history(self):
        self.repository.require('policy')
        with self.repository._connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM policy_activations ORDER BY id DESC')]

    def versions(self):
        self.repository.require('policy')
        with self.repository._connect() as db:
            return [dict(row) for row in db.execute('''SELECT v.id,v.actor,v.reason,v.created_at,
                CASE WHEN v.id=(SELECT version_id FROM policy_active) THEN 'Active'
                  WHEN EXISTS(SELECT 1 FROM policy_activations a WHERE a.version_id=v.id) THEN 'Historical'
                  ELSE 'Draft' END AS status FROM policy_versions v ORDER BY v.id DESC''')]

    def evaluate(self,state):
        self.repository.require('process')
        started=perf_counter()
        result=copy.deepcopy(state)
        try:
            if result.get('policy_evaluation_error'):
                raise ValueError('Policy binding failed.')
            config=validate_config(result.get('policy_config',DEFAULT))
            fields=result.get('extracted_fields',{})
            kind=result.get('document_type','unknown')
            outcomes=[]
            def check(rule,passed,description,*,applicable=True,protected=False):
                outcome='not_applicable' if not applicable else 'passed' if passed else 'failed'
                outcomes.append({'rule_id':rule,'outcome':outcome,'description':description,'protected':protected,
                    'escalates':applicable and not passed,'policy_version_id':result.get('policy_version_id')})
            check('mandatory_fields',all(fields.get(key) for key in config['mandatory_fields'].get(kind,[])) and kind in config['mandatory_fields'],
                'All configured and protected required fields must be present.',protected=True)
            check('field_validation',bool(result.get('validation_passed')),
                'OCR evidence, dates, amounts, arithmetic and contract structure must pass validation.',protected=True)
            check('verified_evidence',not (result.get('evidence_warnings') or result.get('human_evidence_errors') or result.get('validation_warnings')),
                'Unverified extraction or human correction evidence requires review.',protected=True)
            check('po_reference',bool(fields.get('po_reference')),'Invoice PO reference is required by this policy.',applicable=kind=='invoice' and config['require_po_reference'])
            check('po_reconciliation',not result.get('cross_document_issues') and result.get('cross_document_status')=='matched',
                'Referenced PO must uniquely match supplier, currency, amount and current PO restrictions.',applicable=kind=='invoice' and bool(fields.get('po_reference')),protected=True)
            check('supplier_consistency',not any(item.get('code') in {'VENDOR_MISMATCH','SAME_SELLER_CLIENT','SAME_VENDOR_BUYER'} for item in result.get('anomalies',[])),
                'Supplier and buyer roles must be consistent.',applicable=kind in {'invoice','purchase_order'},protected=True)
            check('arithmetic',not any('Total mismatch' in error for error in result.get('validation_errors',[])),
                'Available subtotal and tax must reconcile within '+config['arithmetic_tolerance']+'.',
                applicable=all(fields.get(key) for key in ('subtotal','tax','total')),protected=True)
            check('contract_requirements',bool(result.get('validation_passed')) and not result.get('unsupported_contract_reasons'),
                'Exactly two distinct supported parties and valid required dates; unsupported structures remain blocked.',applicable=kind=='contract',protected=True)
            check('contract_expiration',bool(fields.get('expiration_date')),'Contract expiration date is required by this policy.',applicable=kind=='contract' and config['require_contract_expiration'])
            check('high_value',not any(item.get('code')=='LARGE_AMOUNT' for item in result.get('anomalies',[])),
                'Amount is within the configured currency threshold; no exchange-rate conversion.',applicable=bool(fields.get('total') or fields.get('contract_value')))
            duplicates=[]
            identifier={'invoice':'invoice_number','purchase_order':'po_number','receipt':'receipt_number','contract':'contract_number'}.get(kind)
            party={'invoice':'seller','purchase_order':'vendor','receipt':'seller','contract':'party_a'}.get(kind)
            norm=lambda value:' '.join(str(value or '').casefold().split())
            if identifier and fields.get(identifier):
                with self.repository._connect() as db:
                    for row in db.execute('SELECT id,extracted_data FROM documents WHERE document_type=?',(kind,)):
                        other=json.loads(row['extracted_data'])
                        if row['id']!=result.get('document_id') and norm(other.get(identifier))==norm(fields[identifier]) and norm(other.get(party))==norm(fields.get(party)):
                            duplicates.append(row['id'])
            check('duplicate_identifier',not duplicates,'Same business identifier and party appear on distinct stored sources: '+str(duplicates),applicable=bool(identifier and fields.get(identifier)))
            check('additional_review',not config['escalate_all'],'Additional manual review is required by this policy.')
            check('risk_guard',result.get('risk_level')=='low','Non-low or unresolved risk cannot enter normal processing.',protected=True)
            check('department_routing',kind in config['departments'],'After all checks pass, route to '+config['departments'].get(kind,'Document Operations')+'.')
            failures=[item for item in outcomes if item['escalates']]
            result['rule_outcomes']=outcomes
            result['policy_failed_rules']=[item['rule_id'] for item in failures]
            result['duplicate_business_document_ids']=duplicates
            if failures:
                result['requires_review']=True
            result['policy_evaluation_error']=None
        except Exception:
            # Do not disclose raw storage/config exceptions or allow evaluation failure to approve.
            result.update(requires_review=True,policy_evaluation_error='Policy evaluation unavailable; manual review required.',
                policy_failed_rules=['policy_engine_failure'],rule_outcomes=[{'rule_id':'policy_engine_failure','outcome':'failed',
                'escalates':True,'protected':True,'description':'Policy evaluation failed conservatively.','policy_version_id':result.get('policy_version_id')}])
        result['policy_latency_ms']=(perf_counter()-started)*1000
        result['agent_history']=state.get('agent_history',[])+['business_policy']
        return result

    def reevaluate(self,document_id,expected_revision,version_id,*,actor,reason,confirmed=False):
        actor=self.repository.access.actor(actor,'policy',document_id)
        from idp.review.service import ReviewService
        ReviewService.identity(actor,reason)
        if confirmed is not True:
            raise ValueError('Explicit reevaluation confirmation is required.')
        service=ReviewService(self.repository)
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            document=service._current(db,document_id,expected_revision)
            active=db.execute('SELECT version_id FROM policy_active').fetchone()[0]
            if active!=version_id:
                raise ValueError('Select the current active policy for explicit reevaluation.')
            before=json.loads(document['full_result'])
            state=self.bind(before,version_id)
            state['document_id']=document_id
            state=service.validate(state)
            decision=document['review_decision'] if document['review_decision'] in {'rejected','needs_correction','escalated'} else 'pending'
            # Reevaluation is never a shortcut to departmental processing or an approval.
            state.update(workflow_status='rejected' if decision=='rejected' else 'manual_review',assigned_department='Document Review',requires_review=True,
                routing_reason='Explicit policy reevaluation requires a new human decision; earlier restrictions remain in force.')
            db.execute('UPDATE documents SET full_result=?,workflow_status=?,assigned_department=?,review_decision=?,updated_at=? WHERE id=?',
                (json.dumps(state,ensure_ascii=False),state['workflow_status'],state['assigned_department'],decision,self.repository.timestamp(),document_id))
            status={'rejected':'rejected','needs_correction':'awaiting_correction','escalated':'escalated'}.get(decision,'in_review')
            db.execute('UPDATE review_cases SET case_status=?,updated_at=? WHERE document_id=?',(status,self.repository.timestamp(),document_id))
            event=service.event(db,document,'policy_reevaluation',{'policy_version_id':before.get('policy_version_id'),'decision':document['review_decision']},
                {'policy_version_id':version_id,'decision':decision,'result':state},actor,reason,decision=decision,state=state)
            if document['document_type']=='purchase_order':
                service.invalidate_dependents(db,document_id,'Referenced PO was explicitly reevaluated under a policy; fresh invoice review required.')
        return event

"""Default-deny permissions and SQL row scopes, revalidated against server sessions."""
import json
from idp.security.auth import AccessDenied, AuthService, REVIEW_DEPARTMENT

PERMISSIONS={
    'Administrator':{'account','users','documents','review','assign','policy','analytics','export','source','process','batches','governance','security_audit'},
    'Operations Manager':{'account','analytics'},
    'Finance Reviewer':{'account','documents','review','analytics','export','source'},
    'Procurement Reviewer':{'account','documents','review','analytics','export','source'},
    'Expense Reviewer':{'account','documents','review','analytics','export','source'},
    'Legal Reviewer':{'account','documents','review','analytics','export','source'},
    'Document Reviewer':{'account','documents','review','analytics','export','source'},
    'Auditor':{'account','documents','analytics'},
}
for role in PERMISSIONS:
    if 'analytics' in PERMISSIONS[role] and role!='Auditor': PERMISSIONS[role].add('analytics_export')
    if role=='Administrator' or role in REVIEW_DEPARTMENT: PERMISSIONS[role].add('intake')


class AccessControl:
    def __init__(self,repository):
        self.repository=repository

    def principal(self):
        repo=self.repository
        if repo.internal:
            return {'id':None,'username':'system:internal','role':'Administrator','departments':[]}
        auth=AuthService(repo)
        principal=auth.resolve_hash(repo.session_hash) if repo.session_hash else auth.resolve(repo.session_token)
        if not repo._connection_depth:
            with repo._connect() as db:
                from idp.security.auth import digest
                db.execute('UPDATE auth_sessions SET last_seen=? WHERE token_hash=?',(auth.clock(),repo.session_hash or digest(repo.session_token)))
        return principal

    def require(self,permission):
        principal=self.principal()
        if not self.repository.internal and permission not in PERMISSIONS.get(principal['role'],set()):
            AuthService(self.repository).event('unauthorized_operation','denied',permission,principal['id'])
            raise AccessDenied('This account is not authorized for this operation.')
        return principal

    def scope(self,alias='d',*,mutation=False):
        principal=self.require('review' if mutation else 'analytics')
        if self.repository.internal or principal['role']=='Administrator': return '1=1',[]
        departments=principal['departments']
        if not departments: return '0=1',[]
        placeholders=','.join('?' for _ in departments)
        direct=f"EXISTS(SELECT 1 FROM review_cases scope_case WHERE scope_case.document_id={alias}.id AND scope_case.team IN ({placeholders}))"
        args=list(departments)
        if mutation: return direct,args
        role=principal['role']
        if role in REVIEW_DEPARTMENT:
            readable_teams=[*departments,'Document Review']
            if role=='Finance Reviewer': readable_teams.append('Procurement')
            if role=='Document Reviewer': readable_teams.extend(['Finance','Procurement','Expense Processing','Legal','Document Operations'])
            places=','.join('?' for _ in readable_teams)
            retained=f"EXISTS(SELECT 1 FROM review_cases retained WHERE retained.document_id={alias}.id AND retained.team IN ({places}))"
            direct+=f" OR ({retained} AND (EXISTS(SELECT 1 FROM processing_runs uploaded WHERE uploaded.document_id={alias}.id AND json_extract(uploaded.actor_context,'$.id')=? AND json_extract(uploaded.actor_context,'$.role')=?) OR EXISTS(SELECT 1 FROM review_events handed WHERE handed.document_id={alias}.id AND handed.event_type IN ('handoff','correction') AND json_extract(handed.previous_values,'$.team') IN ({placeholders}))))"
            args.extend([*readable_teams,principal['id'],role,*departments])
        if role=='Finance Reviewer':
            direct+=f" OR ({alias}.document_type='purchase_order' AND EXISTS(SELECT 1 FROM documents related JOIN review_cases related_case ON related_case.document_id=related.id WHERE (related_case.team='Finance' OR (related_case.team IN ('Document Review','Procurement') AND (EXISTS(SELECT 1 FROM processing_runs uploaded WHERE uploaded.document_id=related.id AND json_extract(uploaded.actor_context,'$.id')=? AND json_extract(uploaded.actor_context,'$.role')='Finance Reviewer') OR EXISTS(SELECT 1 FROM review_events handed WHERE handed.document_id=related.id AND handed.event_type='handoff' AND json_extract(handed.previous_values,'$.team')='Finance')))) AND json_extract(related.full_result,'$.matched_document_id')={alias}.id))"
            args.append(principal['id'])
        if role=='Procurement Reviewer':
            direct+=f" OR ({alias}.document_type='invoice' AND coalesce(json_extract({alias}.extracted_data,'$.po_reference'),'')!='' AND (json_extract({alias}.full_result,'$.cross_document_status') IN ('unmatched','ambiguous','mismatch','incomplete') OR EXISTS(SELECT 1 FROM review_cases linked WHERE linked.document_id=json_extract({alias}.full_result,'$.matched_document_id') AND linked.team='Procurement')))"
        return '('+direct+')',args

    def intake(self, state=None, document_id=None, *, force=False):
        principal=self.require('intake')
        if self.repository.internal or principal['role']=='Administrator': return principal
        if force:
            raise AccessDenied('Forced reprocessing requires administrator oversight.')
        if document_id is not None:
            self.document(document_id)
        if state is not None:
            expected={'Finance Reviewer':'invoice','Procurement Reviewer':'purchase_order',
                      'Expense Reviewer':'receipt','Legal Reviewer':'contract'}
            if principal['role'] in expected and state.get('document_type')!=expected[principal['role']]:
                raise AccessDenied('This document type requires intake by its responsible department or an administrator.')
        return principal

    def batch(self,batch_id=None):
        principal=self.require('intake')
        if self.repository.internal or principal['role']=='Administrator': return principal
        if batch_id is not None:
            with self.repository._connect() as db:
                row=db.execute('SELECT submitted_by,actor_context FROM batch_jobs WHERE id=?',(batch_id,)).fetchone()
            if not row or row['submitted_by']!=principal['id'] or json.loads(row['actor_context'] or '{}').get('role')!=principal['role']:
                raise AccessDenied('Processing job is unavailable or belongs to another employee.')
        return principal

    def document(self,document_id,permission='documents',*,mutation=False):
        principal=self.require(permission)
        scope,args=self.scope(mutation=mutation)
        with self.repository._connect() as db:
            row=db.execute('SELECT d.id FROM documents d WHERE d.id=? AND '+scope,[document_id,*args]).fetchone()
        if not row:
            # Unknown and unauthorized IDs give the same response.
            if not self.repository.internal:
                AuthService(self.repository).event('document_access','denied','document',principal['id'])
            raise AccessDenied('Document is unavailable or outside your authorized scope.')
        return principal

    def actor(self,actor,permission,document_id=None):
        principal=self.document(document_id,permission,mutation=True) if document_id is not None else self.require(permission)
        if self.repository.internal: return actor
        canonical='user:'+str(principal['id'])+':'+principal['username']
        if actor not in (None,'',canonical):
            AuthService(self.repository).event('forged_actor','denied',permission,principal['id'])
            raise AccessDenied('Actor identity must match the authenticated account.')
        if document_id is not None and permission=='review' and principal['role']!='Administrator':
            with self.repository._connect() as db:
                case=db.execute('SELECT assignee FROM review_cases WHERE document_id=?',(document_id,)).fetchone()
            if case and case['assignee'] and case['assignee']!=canonical:
                raise AccessDenied('This case is assigned to another reviewer.')
        return canonical

    def attribution(self,db,table,event_id):
        if not self.repository.internal:
            principal=self.principal()
            db.execute('INSERT INTO event_identities VALUES(?,?,?)',(table,event_id,principal['id']))


def scoped_where(repository,where,args,permission='analytics'):
    repository.require(permission)
    scope,extra=repository.access.scope(mutation=permission=='review')
    return where+(' AND ' if where else ' WHERE ')+scope,[*args,*extra]

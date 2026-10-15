"""Same-origin, loopback HTTP adapter over authenticated IDP services."""
import os
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from datetime import date
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field

from idp.storage.repository import DocumentRepository
from idp.storage.operations import DocumentFilters, OperationsQueries
from idp.security.auth import AccessDenied, AuthenticationError, AuthService
from idp.security.access import PERMISSIONS
from idp.security.downloads import DownloadService
from idp.review.service import ReviewService, ReviewConflict, UnsafeApproval
from idp.batch.service import BatchService, safe_failure
from idp.policy.service import PolicyService

COOKIE = 'idp_session'


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_max_length=4000)


class Login(Input):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class Mutation(Input):
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1)
    confirmed: Literal[True]


class Decision(Mutation):
    decision: Literal['approved', 'rejected', 'needs_correction', 'escalated']
    notes: str = ''


class Correction(Input):
    changes: dict[str, str | None]
    evidence: dict[str, str]


class SaveCorrection(Correction, Mutation):
    pass


class Management(Mutation):
    action: Literal['claim', 'assign', 'status', 'priority']
    team: str | None = None
    assignee: str | None = None
    status: str | None = None
    priority: str | None = None


class Download(Input):
    kind: Literal['source','document_json','analytics_json','filtered_json','filtered_csv','batch_json','batch_csv']
    resource: dict


class PolicyDraft(Input):
    config: dict
    reason: str = Field(min_length=1)


class Activation(Input):
    preview_id: int
    reason: str = Field(min_length=1)
    confirmed: Literal[True]


class Reevaluation(Mutation):
    version_id: int


class UserInput(Login):
    role: str
    departments: list[str]


class UserUpdate(Input):
    expected_revision: int
    active: bool
    role: str
    departments: list[str]
    confirmed: Literal[True]


class Password(Input):
    current: str = Field(max_length=128)
    new: str = Field(min_length=12,max_length=128)


class FiltersInput(Input):
    document_type: str = ''
    department: str = ''
    status: str = ''
    review_decision: str = ''
    start_date: date | None = None
    end_date: date | None = None
    search: str = Field(default='',max_length=200)
    currency: str = Field(default='',max_length=3)
    min_amount: float | None = None
    max_amount: float | None = None
    batch_id: str = ''


def filters_for(request):
    values={key:value for key,value in request.query_params.items() if key in FiltersInput.model_fields and value!=''}
    return DocumentFilters(**FiltersInput(**values).model_dump())


def create_app(database_path=None, *, pipeline_factory=None, frontend=None):
    app = FastAPI(title='Document Operations', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.database_path = str(database_path or os.getenv('IDP_DATABASE_PATH', 'data/idp.db'))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1','localhost','testserver'])

    @app.middleware('http')
    async def protections(request, call_next):
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin = request.headers.get('origin')
            if request.headers.get('x-idp-request') != '1' or (origin and origin != str(request.base_url).rstrip('/')):
                return JSONResponse({'detail':'Same-origin request required.'}, status_code=403)
        try:
            length=int(request.headers.get('content-length','0') or 0)
        except ValueError:
            return JSONResponse({'detail':'Invalid request length.'},status_code=400)
        if request.method=='POST' and 'content-length' not in request.headers:
            return JSONResponse({'detail':'A bounded request length is required.'},status_code=411)
        if length > 105 * 1024 * 1024:
            return JSONResponse({'detail':'Upload exceeds the batch size limit.'},status_code=413)
        response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.exception_handler(AccessDenied)
    async def denied(request, error):
        return JSONResponse({'detail':str(error)},status_code=403)

    @app.exception_handler(AuthenticationError)
    async def authentication(request, error):
        return JSONResponse({'detail':str(error)},status_code=401)

    @app.exception_handler(ReviewConflict)
    async def conflict(request, error):
        return JSONResponse({'detail':str(error)},status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({'detail':'The operation could not be accepted. Check the fields, evidence, revision and required confirmations.'},status_code=400)

    @app.exception_handler(UnsafeApproval)
    async def unsafe_approval(request, error):
        return JSONResponse({'detail':str(error)},status_code=400)

    @app.exception_handler(Exception)
    async def failed(request, error):
        return JSONResponse({'detail':'Operation failed. Saved progress is retained; check the source or service configuration.'},status_code=500)

    def repository(request: Request):
        repo = DocumentRepository(app.state.database_path, session_token=request.cookies.get(COOKIE))
        try:
            repo.require('account')
        except AccessDenied:
            raise HTTPException(401,'Sign in again. Your session may have expired.') from None
        return repo

    Repo = Annotated[DocumentRepository, Depends(repository)]

    def pipeline(repo):
        if pipeline_factory:
            return pipeline_factory(repo)
        from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
        return AgenticDocumentPipeline(repo.db_path,session_token=repo.session_token)

    @app.post('/api/login')
    def login(body: Login, response: Response):
        token = AuthService(DocumentRepository(app.state.database_path)).login(body.username,body.password)
        response.set_cookie(COOKIE,token,httponly=True,samesite='strict',secure=False,max_age=3600,path='/')
        return {'ok':True}

    @app.get('/api/session')
    def session(repo: Repo):
        principal = repo.require('account')
        return {**principal,'permissions':sorted(PERMISSIONS.get(principal['role'],set()))}

    @app.post('/api/logout')
    def logout(response: Response, repo: Repo):
        AuthService(repo).logout(repo.session_token)
        response.delete_cookie(COOKIE,path='/')
        return {'ok':True}

    @app.get('/api/overview')
    def overview(request: Request, repo: Repo):
        return OperationsQueries(repo).overview(filters_for(request))

    @app.get('/api/documents')
    def documents(request: Request, repo: Repo, search: str='', document_type: str='', department: str='', status: str='',
                  review_decision: str='', page: int=1, sort: str='Newest first',start_date:date|None=None,
                  end_date:date|None=None,currency:str='',min_amount:float|None=None,max_amount:float|None=None,batch_id:str=''):
        repo.require('documents')
        rows,total=OperationsQueries(repo).page(filters_for(request),page=max(1,page),sort=sort)
        return {'rows':rows,'total':total}

    @app.get('/api/options')
    def options(repo: Repo):
        return OperationsQueries(repo).options()

    @app.get('/api/documents/{document_id}')
    def document(document_id: int, repo: Repo):
        repo.access.document(document_id)
        result=repo.get_document(document_id)
        with repo._connect() as db:
            sources=[dict(row) for row in db.execute('SELECT id,filename,state,retain_until FROM batch_items WHERE document_id=?',(document_id,))]
            versions=[dict(row) for row in db.execute('SELECT id,origin,captured_at,original_state FROM processing_versions WHERE document_id=? ORDER BY id DESC',(document_id,))]
            runs=[dict(row) for row in db.execute('SELECT id,processed_at,is_duplicate,result_snapshot FROM processing_runs WHERE document_id=? ORDER BY id DESC',(document_id,))]
        from idp.agents.validation_agent import ValidationAgent
        from idp.review.service import EDITABLE
        kind=result['full_result'].get('document_type')
        fields=result['full_result'].get('extracted_fields',{})
        editable=sorted((set(fields)|set(ValidationAgent.REQUIRED_FIELDS.get(kind,[]))|set(ValidationAgent.OPTIONAL_FIELDS.get(kind,[])))&EDITABLE)
        return {**result,'case':ReviewService(repo).case(document_id),'events':ReviewService(repo).history(document_id),
                'sources':sources,'versions':versions,'runs':runs,'editable_fields':{key:fields.get(key) for key in editable}}

    @app.get('/api/review')
    def queue(request: Request, repo: Repo, search: str='', team: str='', risk: str='', case_status: str='', assignee: str='',
              include_closed: bool=False, page: int=1):
        rows,total=ReviewService(repo).queue(filters_for(request),team=team,risk=risk,case_status=case_status,
            assignee=assignee,include_closed=include_closed,page=max(1,page))
        return {'rows':rows,'total':total}

    @app.post('/api/documents/{document_id}/decision')
    def decide(document_id: int, body: Decision, repo: Repo):
        event=ReviewService(repo).decide(document_id,body.expected_revision,body.decision,actor=None,reason=body.reason,notes=body.notes)
        return {'event_id':event}

    @app.post('/api/documents/{document_id}/correction-preview')
    def preview(document_id: int, body: Correction, repo: Repo):
        return ReviewService(repo).preview_correction(document_id,body.changes,body.evidence)

    @app.post('/api/documents/{document_id}/correction')
    def correct(document_id: int, body: SaveCorrection, repo: Repo):
        return {'event_id':ReviewService(repo).apply_correction(document_id,body.expected_revision,body.changes,body.evidence,
            actor=None,reason=body.reason)}

    @app.post('/api/documents/{document_id}/case')
    def manage(document_id: int, body: Management, repo: Repo):
        return {'event_id':ReviewService(repo).manage(document_id,body.expected_revision,body.action,actor=None,reason=body.reason,
            team=body.team,assignee=body.assignee,status=body.status,priority=body.priority)}

    @app.post('/api/downloads')
    def grant(body: Download, repo: Repo):
        if 'filters' in body.resource:
            values={key:value for key,value in body.resource['filters'].items() if value!=''}
            validated=FiltersInput(**values)
            body.resource['filters']=validated.model_dump(mode='json')
        return {'grant':DownloadService(repo).grant(body.kind,body.resource)}

    @app.post('/api/downloads/{token}')
    def download(token: str, repo: Repo):
        # The existing grant service revalidates expiry, source hash and user scopes.
        # Additionally require the requesting browser to own the grant.
        from idp.security.auth import digest
        with repo._connect() as db:
            row=db.execute('SELECT session_hash FROM download_grants WHERE grant_hash=?',(digest(token),)).fetchone()
        if not row or row['session_hash']!=digest(repo.session_token):
            raise AccessDenied('Download unavailable.')
        data,name,mime=DownloadService(repo).redeem(token)
        return Response(data,media_type=mime,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(name,safe='')})

    @app.get('/api/batches')
    def batches(repo: Repo):
        return BatchService(repo).history()

    @app.get('/api/batches/{batch_id}')
    def batch(batch_id: str, repo: Repo):
        service=BatchService(repo)
        summary=service.summary(batch_id)
        items=service.items(batch_id)
        return {**summary,'attempts':{item['id']:service.attempts(item['id']) for item in items}}

    @app.post('/api/uploads/{mode}')
    async def upload(mode: Literal['single','batch','preview'], request: Request, repo: Repo):
        repo.require('process' if mode=='single' else 'batches')
        from idp.batch.ingestion import preview,inspect_file
        from starlette.concurrency import run_in_threadpool
        async with request.form(max_files=50,max_fields=10) as form:
            files=[]
            for file in form.getlist('files'):
                if not hasattr(file,'read'): raise ValueError('A document file is required.')
                content=await file.read(20*1024*1024+1)
                if len(content)>20*1024*1024: raise ValueError('Document exceeds size limit.')
                files.append((file.filename,content))
            if not files or sum(len(data) for _,data in files)>100*1024*1024: raise ValueError('Invalid batch size.')
            if mode=='preview':
                rows,_=await run_in_threadpool(preview,files,repo)
                return {'rows':rows}
            if form.get('consent')!='true': raise ValueError('External AI consent is required.')
            force=form.get('force')=='true'
            if mode=='batch':
                batch_id=await run_in_threadpool(BatchService(repo).submit,files,request_key=str(form.get('request_key','')),
                    name=str(form.get('name','Document batch')),description=str(form.get('description','')),force=force)
                return {'batch_id':batch_id}
            if len(files)!=1: raise ValueError('Choose one document.')
            info=await run_in_threadpool(inspect_file,*files[0])
            def process():
                with tempfile.TemporaryDirectory(prefix='idp_web_') as folder:
                    path=Path(folder)/('upload'+info['extension']);path.write_bytes(files[0][1])
                    try:
                        return pipeline(repo).process(path,original_filename=info['filename'],force_reprocess=force,ai_consent=True)
                    except Exception as error:
                        raise HTTPException(502,safe_failure(error)[1]) from None
            return await run_in_threadpool(process)

    @app.post('/api/batches/{batch_id}/run')
    def run_batch(batch_id: str, body: dict, repo: Repo):
        repo.require('batches')
        if body.get('consent') is not True: raise ValueError('External AI consent required.')
        try:
            BatchService(repo).run(lambda:pipeline(repo),batch_id,ai_consent=True)
        except RuntimeError:
            raise HTTPException(409,'Another worker is active. Refresh to monitor saved progress.') from None
        return {'ok':True}

    @app.post('/api/batch-items/{item_id}/retry')
    def retry(item_id: int, repo: Repo):
        BatchService(repo).retry(item_id)
        return {'ok':True}

    @app.get('/api/analytics')
    def analytics(request: Request, repo: Repo):
        from idp.storage.intelligence import IntelligenceQueries
        return IntelligenceQueries(repo).report(filters_for(request))

    @app.get('/api/policies')
    def policies(repo: Repo):
        repo.require('policy')
        service=PolicyService(repo)
        return {'active':service.active(),'versions':service.versions(),'history':service.history()}

    @app.post('/api/policies')
    def draft(body: PolicyDraft, repo: Repo):
        return {'version_id':PolicyService(repo).draft(body.config,actor=None,reason=body.reason)}

    @app.post('/api/policies/{version_id}/preview')
    def policy_preview(version_id:int,repo:Repo):
        return PolicyService(repo).preview(version_id)

    @app.post('/api/policies/{version_id}/activate')
    def activate(version_id:int,body:Activation,repo:Repo):
        return {'generation':PolicyService(repo).activate(version_id,body.preview_id,actor=None,reason=body.reason,confirmed=body.confirmed)}

    @app.post('/api/documents/{document_id}/reevaluate')
    def reevaluate(document_id:int,body:Reevaluation,repo:Repo):
        return PolicyService(repo).reevaluate(document_id,body.expected_revision,body.version_id,actor=None,reason=body.reason,confirmed=body.confirmed)

    @app.get('/api/users')
    def users(repo:Repo):
        from idp.security.auth import ROLES,DEPARTMENTS
        return {'users':AuthService(repo).users(),'roles':ROLES,'departments':DEPARTMENTS}

    @app.post('/api/users')
    def user_create(body:UserInput,repo:Repo):
        return {'id':AuthService(repo).create_user(body.username,body.password,body.role,body.departments)}

    @app.post('/api/users/{user_id}')
    def user_update(user_id:int,body:UserUpdate,repo:Repo):
        AuthService(repo).update_user(user_id,body.expected_revision,active=body.active,role=body.role,departments=body.departments)
        return {'ok':True}

    @app.post('/api/password')
    def password(body:Password,repo:Repo,response:Response):
        AuthService(repo).change_password(body.current,body.new)
        response.delete_cookie(COOKIE,path='/')
        return {'ok':True}

    @app.get('/api/audit')
    def audit(repo:Repo):
        repo.require('security_audit')
        with repo._connect() as db:
            return [dict(row) for row in db.execute('SELECT id,event_type,user_id,outcome,resource,created_at FROM security_events ORDER BY id DESC LIMIT 100')]

    @app.get('/api/retention')
    def retention(repo:Repo):
        from idp.security.governance import GovernanceService
        return GovernanceService(repo).candidates()

    @app.post('/api/retention/{item_id}')
    def cleanup(item_id:int,body:dict,repo:Repo):
        from idp.security.governance import GovernanceService
        GovernanceService(repo).cleanup(item_id,confirmed=body.get('confirmed') is True)
        return {'ok':True}

    root=Path(frontend) if frontend else Path(__file__).resolve().parents[3]/'frontend'/'dist'
    if root.is_dir():
        app.mount('/', StaticFiles(directory=root,html=True),name='frontend')
    return app


def main():
    from dotenv import load_dotenv
    import uvicorn
    load_dotenv()
    uvicorn.run(create_app(),host='127.0.0.1',port=int(os.getenv('IDP_WEB_PORT','8000')),access_log=False)


if __name__=='__main__':
    main()

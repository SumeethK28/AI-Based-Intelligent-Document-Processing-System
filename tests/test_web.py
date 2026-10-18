"""Real HTTP adapter and SQLite tests; model calls use the existing simulated fixture."""
import io
import secrets
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

sys.path.insert(0,str(Path(__file__).resolve().parent/'components'))
from _test_support import PipelineFixture
from idp.security.auth import AuthService
from idp.web.api import create_app


class WebTests(PipelineFixture):
    def setUp(self):
        super().setUp()
        self.repo=self.pipeline.repository
        self.invoice=self.process('invoice.txt','invoice',{'invoice_number':'INV-WEB','seller':'Cedar Supply',
            'client':'Orbit Research','issue_date':'2026-10-01','total':'INR 100.00'})['document_id']
        self.contract=self.process('contract.txt','contract',{'contract_title':'Services Agreement','party_a':'Cedar',
            'party_b':'Orbit','effective_date':'2026-10-01','governing_law':'India'})['document_id']
        self.password=secrets.token_urlsafe(24)
        auth=AuthService(self.repo)
        auth.create_user('web-admin',self.password,'Administrator',[])
        auth.create_user('web-finance',self.password,'Finance Reviewer',[])
        self.app=create_app(self.repo.db_path)
        self.client=TestClient(self.app)
        self.client.headers['x-idp-request']='1'
        self.login()

    def login(self,username='web-admin',client=None):
        client=client or self.client
        response=client.post('/api/login',json={'username':username,'password':self.password})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        return response

    def test_scoped_document_read_and_cross_department_denial(self):
        self.login('web-finance')
        self.assertEqual(self.client.get(f'/api/documents/{self.invoice}').status_code,200)
        self.assertEqual(self.client.get(f'/api/documents/{self.contract}').status_code,403)
        rows=self.client.get('/api/documents').json()['rows']
        self.assertNotIn(self.contract,[row['id'] for row in rows])

    def test_configuration_failure_guidance_is_admin_only_and_source_is_retained(self):
        import os
        from idp.llm.provider import GroqProvider
        from idp.batch.service import BatchService
        from idp.storage.repository import DocumentRepository
        from idp.security import INTERNAL
        app=create_app(self.repo.db_path,pipeline_factory=lambda repo:GroqProvider())
        client=TestClient(app,headers={'x-idp-request':'1'})
        for username in ('web-admin','web-finance'):
            with self.subTest(username=username):
                self.login(username,client)
                stream=io.BytesIO();doc=canvas.Canvas(stream);doc.drawString(50,750,'Synthetic configuration test');doc.save()
                response=client.post('/api/uploads/batch',files=[('files',('test.pdf',stream.getvalue(),'application/pdf'))],data={'consent':'true','request_key':username})
                self.assertEqual(response.status_code,200,response.text)
                job=response.json()['batch_id']
                with patch.dict(os.environ,{'GROQ_API_KEY':''}):
                    run=client.post(f'/api/batches/{job}/run',json={'consent':True})
                self.assertEqual(run.status_code,200,run.text)
                response=client.get(f'/api/batches/{job}')
                self.assertEqual(response.status_code,200)
                item=response.json()['items'][0]
                self.assertEqual(item['error_category'],'configuration')
                self.assertNotIn('source',item['safe_error'].lower())
                if username=='web-admin':
                    self.assertIn('GROQ_API_KEY',item['configuration_guidance'])
                    self.assertIn('Restart',item['configuration_guidance'])
                else:
                    self.assertNotIn('configuration_guidance',item)
                    self.assertNotIn('GROQ_API_KEY',response.text)
                service=BatchService(DocumentRepository(self.repo.db_path,_capability=INTERNAL))
                self.assertEqual(service.source(service.items(job)[0]).read_bytes(),stream.getvalue())
                self.assertEqual(len(service.attempts(item['id'])),1)

    def test_single_upload_removes_temporary_source_on_success_and_failure_without_results(self):
        import tempfile
        from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
        temporary=[]
        actual=tempfile.TemporaryDirectory
        def directory(*args,**kwargs):
            result=actual(*args,dir=self.root,**kwargs)
            temporary.append(Path(result.name))
            return result
        self.llm.kind='invoice'
        self.llm.fields={'invoice_number':'TEMP-1','seller':'Cedar','client':'Orbit','issue_date':'2026-10-01','total':'INR 100.00'}
        self.app=create_app(self.repo.db_path,pipeline_factory=lambda repo:AgenticDocumentPipeline(repo.db_path,baseline=self.baseline,llm=self.llm,session_token=repo.session_token))
        client=TestClient(self.app,headers={'x-idp-request':'1'});self.login(client=client)
        stream=io.BytesIO();pdf=canvas.Canvas(stream);pdf.drawString(50,750,'Synthetic cleanup invoice');pdf.save()
        results_before={str(p) for p in Path('results').iterdir()} if Path('results').exists() else set()
        def upload():
            return client.post('/api/uploads/single',files=[('files',('invoice.pdf',stream.getvalue(),'application/pdf'))],data={'consent':'true'})
        with patch('idp.web.api.tempfile.TemporaryDirectory',side_effect=directory):
            self.assertEqual(upload().status_code,200)
            with patch.object(self.baseline,'process',side_effect=ValueError('Synthetic OCR failure')):
                response=client.post('/api/uploads/single',files=[('files',('invoice.pdf',stream.getvalue(),'application/pdf'))],data={'consent':'true','force':'true'})
                self.assertEqual(response.status_code,502)
        self.assertEqual(len(temporary),2)
        self.assertTrue(all(not p.exists() for p in temporary))
        self.assertEqual({str(p) for p in Path('results').iterdir()} if Path('results').exists() else set(),results_before)

    def test_review_revision_permission_and_safe_approval(self):
        self.login('web-finance')
        payload={'expected_revision':999,'reason':'Reviewed evidence','confirmed':True,'decision':'rejected'}
        self.assertEqual(self.client.post(f'/api/documents/{self.invoice}/decision',json=payload).status_code,409)
        payload['expected_revision']=self.repo.get_document(self.invoice)['revision']
        self.assertEqual(self.client.post(f'/api/documents/{self.contract}/decision',json=payload).status_code,403)
        response=self.client.post(f'/api/documents/{self.invoice}/decision',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.repo.get_document(self.invoice)['review_decision'],'rejected')
        self.assertEqual(self.client.post(f'/api/documents/{self.invoice}/decision',json=payload).status_code,409)

    def test_download_is_single_use_session_bound_and_revoked(self):
        body={'kind':'document_json','resource':{'document_id':self.invoice}}
        grant=self.client.post('/api/downloads',json=body).json()['grant']
        other=TestClient(self.app,headers={'x-idp-request':'1'})
        self.login(client=other)
        self.assertEqual(other.post('/api/downloads/'+grant).status_code,403)
        response=self.client.post('/api/downloads/'+grant)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['extracted_fields']['invoice_number'],'INV-WEB')
        self.assertEqual(self.client.post('/api/downloads/'+grant).status_code,403)
        grant=self.client.post('/api/downloads',json=body).json()['grant']
        self.client.post('/api/logout')
        self.assertEqual(self.client.post('/api/downloads/'+grant).status_code,401)

    def test_cookie_csrf_and_unauthenticated_guards(self):
        self.assertEqual(TestClient(self.app).get('/api/overview').status_code,401)
        self.assertEqual(self.client.post('/api/logout',headers={'origin':'https://untrusted.invalid'}).status_code,403)
        self.client.headers.pop('x-idp-request')
        self.assertEqual(self.client.post('/api/logout').status_code,403)
        self.assertEqual(self.client.get('/api/session').status_code,200)

    def test_upload_duplicate_force_and_batch_worker_restart(self):
        from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
        self.llm.kind='invoice'
        self.llm.fields={'invoice_number':'INV-UPLOAD','seller':'Cedar','client':'Orbit','issue_date':'2026-10-01','total':'INR 300.00'}
        self.app=create_app(self.repo.db_path,pipeline_factory=lambda repo:AgenticDocumentPipeline(repo.db_path,
            baseline=self.baseline,llm=self.llm,session_token=repo.session_token))
        self.client=TestClient(self.app,headers={'x-idp-request':'1'})
        self.login()
        stream=io.BytesIO();pdf=canvas.Canvas(stream);pdf.drawString(50,750,'Synthetic invoice');pdf.save()
        content=stream.getvalue()
        def upload(mode,**data):
            return self.client.post('/api/uploads/'+mode,files=[('files',('invoice.pdf',content,'application/pdf'))],data={'consent':'true',**data})
        first=upload('single');self.assertEqual(first.status_code,200,first.text)
        count=self.llm.calls
        duplicate=upload('single');self.assertTrue(duplicate.json()['duplicate']);self.assertEqual(self.llm.calls,count)
        forced=upload('single',force='true');self.assertEqual(forced.status_code,200,forced.text);self.assertGreater(self.llm.calls,count)
        preview=upload('preview');self.assertTrue(preview.json()['rows'][0]['accepted'])
        batch=upload('batch',request_key='http-batch-restart').json()['batch_id']
        self.assertEqual(upload('batch',request_key='http-batch-restart').json()['batch_id'],batch)
        response=self.client.post('/api/batches/'+batch+'/run',json={'consent':True})
        self.assertEqual(response.status_code,200,response.text)
        count=self.llm.calls
        self.assertEqual(self.client.post('/api/batches/'+batch+'/run',json={'consent':True}).status_code,200)
        self.assertEqual(self.llm.calls,count)
        self.assertEqual(self.client.get('/api/batches/'+batch).json()['counts']['duplicate'],1)

    def test_unified_one_or_many_uploads_retain_sources_and_resume_safely(self):
        from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
        self.llm.kind='invoice'
        self.llm.fields={'invoice_number':'INV-UNIFIED','seller':'Cedar','client':'Orbit',
                         'issue_date':'2026-10-01','total':'INR 300.00'}
        app=create_app(self.repo.db_path,pipeline_factory=lambda repo:AgenticDocumentPipeline(repo.db_path,
            baseline=self.baseline,llm=self.llm,session_token=repo.session_token))
        self.client=TestClient(app,headers={'x-idp-request':'1'})
        self.login()
        for size in (1,2):
            with self.subTest(files=size):
                files=[]
                for number in range(size):
                    stream=io.BytesIO();pdf=canvas.Canvas(stream)
                    pdf.drawString(50,750,f'Synthetic upload {size}, file {number}');pdf.save()
                    files.append(('files',(f'upload-{size}-{number}.pdf',stream.getvalue(),'application/pdf')))
                calls=self.llm.calls
                checked=self.client.post('/api/uploads/preview',files=files)
                self.assertEqual(checked.status_code,200,checked.text)
                self.assertTrue(all(row['accepted'] for row in checked.json()['rows']))
                self.assertEqual(self.llm.calls,calls)
                submitted=self.client.post('/api/uploads/batch',files=files,
                    data={'consent':'true','request_key':f'unified-{size}','name':f'Upload {size}'})
                self.assertEqual(submitted.status_code,200,submitted.text)
                job=submitted.json()['batch_id']
                before=self.client.get(f'/api/batches/{job}').json()
                self.assertEqual(before['counts']['queued'],size)
                self.assertEqual(self.client.post(f'/api/batches/{job}/run',json={'consent':False}).status_code,400)
                processed=self.client.post(f'/api/batches/{job}/run',json={'consent':True})
                self.assertEqual(processed.status_code,200,processed.text)
                summary=self.client.get(f'/api/batches/{job}').json()
                self.assertEqual(summary['counts']['queued']+summary['counts']['processing']+summary['counts']['failed'],0)
                self.assertEqual(len(summary['items']),size)
                for item in summary['items']:
                    self.assertIsNotNone(item['document_id'])
                    detail=self.client.get(f"/api/documents/{item['document_id']}").json()
                    self.assertTrue(any(source['id']==item['id'] for source in detail['sources']))
                grant=self.client.post('/api/downloads',json={'kind':'source','resource':{'item_id':summary['items'][0]['id']}}).json()['grant']
                self.assertEqual(self.client.post('/api/downloads/'+grant).content,files[0][1][1])
                calls=self.llm.calls
                self.assertEqual(self.client.post(f'/api/batches/{job}/run',json={'consent':True}).status_code,200)
                self.assertEqual(self.llm.calls,calls)

    def test_policy_lifecycle_and_administration_guards(self):
        config=self.client.get('/api/policies').json()['active']['config'];config['require_po_reference']=True
        version=self.client.post('/api/policies',json={'config':config,'reason':'HTTP policy test'}).json()['version_id']
        preview=self.client.post(f'/api/policies/{version}/preview',json={})
        self.assertEqual(preview.status_code,200,preview.text)
        response=self.client.post(f'/api/policies/{version}/activate',json={'preview_id':preview.json()['id'],'reason':'Reviewed preview','confirmed':True})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/policies').json()['active']['id'],version)
        self.login('web-finance')
        for route in ('/api/policies','/api/users','/api/audit','/api/retention'):
            self.assertEqual(self.client.get(route).status_code,403,route)
        self.assertEqual(self.client.post('/api/policies',json={'config':config,'reason':'Denied'}).status_code,403)

    def test_filters_and_scoped_csv_json_match(self):
        self.login('web-finance')
        query='document_type=invoice&currency=INR&min_amount=90&max_amount=110'
        self.assertEqual(self.client.get('/api/documents?'+query).json()['total'],1)
        self.assertEqual(self.client.get('/api/documents?min_amount=200').json()['total'],0)
        filters={'document_type':'invoice','currency':'INR','min_amount':'90','max_amount':'110'}
        exports=[]
        for kind in ('filtered_json','filtered_csv'):
            grant=self.client.post('/api/downloads',json={'kind':kind,'resource':{'filters':filters}}).json()['grant']
            response=self.client.post('/api/downloads/'+grant)
            self.assertEqual(response.status_code,200,response.text)
            exports.append(response)
        import csv
        payload=exports[0].json();rows=list(csv.DictReader(io.StringIO(exports[1].text)))
        self.assertEqual([row['id'] for row in payload],[int(row['id']) for row in rows])
        self.assertEqual(len(rows),1)

    def test_retained_source_hash_and_scoped_batch_progress(self):
        from idp.batch.service import BatchService
        stream=io.BytesIO()
        pdf=canvas.Canvas(stream);pdf.drawString(50,750,'Synthetic invoice');pdf.save()
        service=BatchService(self.repo)
        batch=service.submit([('synthetic.pdf',stream.getvalue())],request_key='web-proof')
        item=service.items(batch)[0]
        with self.repo.connect() as db:
            db.execute('UPDATE batch_items SET document_id=? WHERE id=?',(self.invoice,item['id']))
        self.assertEqual(self.client.get('/api/batches/'+batch).status_code,200)
        self.login('web-finance')
        self.assertEqual(self.client.get('/api/batches/'+batch).status_code,403)
        grant=self.client.post('/api/downloads',json={'kind':'source','resource':{'item_id':item['id']}}).json()['grant']
        self.assertEqual(self.client.post('/api/downloads/'+grant).content,stream.getvalue())
        grant=self.client.post('/api/downloads',json={'kind':'source','resource':{'item_id':item['id']}}).json()['grant']
        service.source(item).write_bytes(b'changed')
        self.assertEqual(self.client.post('/api/downloads/'+grant).status_code,400)

    def test_unconfigured_database_has_no_browser_bootstrap_or_default_account(self):
        from idp.storage.repository import DocumentRepository
        from idp.security import INTERNAL
        empty = self.root / 'unconfigured.db'
        client = TestClient(create_app(empty), headers={'x-idp-request': '1'})
        response = client.post('/api/login', json={'username': 'admin', 'password': self.password})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(client.get('/api/users').status_code, 401)
        self.assertIn(client.post('/api/bootstrap', json={}).status_code, (404, 405))
        repo = DocumentRepository(empty, _capability=INTERNAL)
        with repo.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_login_permissions_and_logout_revoke_saved_cookie(self):
        response = self.client.post('/api/login', json={'username': 'web-finance', 'password': 'wrong-input'})
        self.assertEqual(response.status_code, 401)
        self.login('web-finance')
        permissions = self.client.get('/api/session').json()['permissions']
        self.assertIn('review', permissions)
        self.assertNotIn('users', permissions)
        self.assertNotIn('process', permissions)
        cookie = self.client.cookies.get('idp_session')
        self.assertEqual(self.client.post('/api/logout').status_code, 200)
        self.assertEqual(self.client.get('/api/session').status_code, 401)
        replay = TestClient(self.app, headers={'x-idp-request': '1'})
        replay.cookies.set('idp_session', cookie)
        self.assertEqual(replay.get('/api/session').status_code, 401)

    def test_auditor_reads_history_but_cannot_mutate_or_export(self):
        payload = {'expected_revision': self.repo.get_document(self.invoice)['revision'],
                   'reason': 'Auditable decision', 'confirmed': True, 'decision': 'rejected'}
        self.assertEqual(self.client.post(f'/api/documents/{self.invoice}/decision', json=payload).status_code, 200)
        AuthService(self.repo).create_user('web-auditor', self.password, 'Auditor', ['Finance'])
        self.login('web-auditor')
        detail = self.client.get(f'/api/documents/{self.invoice}')
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertTrue(detail.json()['events'])
        self.assertEqual(self.client.post(f'/api/documents/{self.invoice}/decision', json=payload).status_code, 403)
        self.assertEqual(self.client.post('/api/downloads', json={'kind': 'document_json',
                         'resource': {'document_id': self.invoice}}).status_code, 403)
        self.assertEqual(self.client.get(f'/api/documents/{self.contract}').status_code, 403)

    def test_read_destinations_and_details_do_not_initialize_model(self):
        with patch('idp.pipeline.agentic_pipeline.AgenticDocumentPipeline', side_effect=AssertionError('Unexpected model initialization')):
            for route in ('/api/overview', '/api/documents', '/api/review', '/api/analytics',
                          '/api/policies', '/api/users', '/api/audit', '/api/retention'):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200, (route, response.text))
            detail = self.client.get(f'/api/documents/{self.invoice}').json()
        self.assertEqual(detail['sources'], [])
        self.assertEqual(detail['full_result']['extracted_fields']['invoice_number'], 'INV-WEB')
        self.assertIn('field_evidence', detail['full_result'])
        self.assertIn('validation_passed', detail['full_result'])
        self.assertIn('workflow_status', detail['full_result'])
        self.assertIn('routing_reason', detail['full_result'])

    def test_review_notes_are_document_scoped_and_actor_cannot_be_spoofed(self):
        original = self.repo.get_document(self.contract)
        payload = {'expected_revision': self.repo.get_document(self.invoice)['revision'],
                   'reason': 'Invoice only', 'confirmed': True, 'decision': 'rejected', 'notes': 'Invoice-specific notes'}
        forged = self.client.post(f'/api/documents/{self.invoice}/decision', json={**payload, 'actor': 'another-user'})
        self.assertEqual(forged.status_code, 422)
        response = self.client.post(f'/api/documents/{self.invoice}/decision', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        for _ in range(2):
            invoice = self.client.get(f'/api/documents/{self.invoice}').json()
            contract = self.client.get(f'/api/documents/{self.contract}').json()
            self.assertEqual(invoice['review_notes'], 'Invoice-specific notes')
            self.assertEqual(contract['review_notes'], original['review_notes'])
            self.assertEqual(contract['revision'], original['revision'])

    def test_batch_failed_item_http_retry_after_app_restart(self):
        from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
        self.llm.kind = 'receipt'
        self.llm.fields = {'seller': 'Shop', 'issue_date': '2026-10-01', 'total': 'INR 20.00'}
        def factory(repo):
            return AgenticDocumentPipeline(repo.db_path, baseline=self.baseline, llm=self.llm, session_token=repo.session_token)
        self.client = TestClient(create_app(self.repo.db_path, pipeline_factory=factory), headers={'x-idp-request': '1'})
        self.login()
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream); pdf.drawString(50, 750, 'Synthetic receipt'); pdf.save()
        response = self.client.post('/api/uploads/batch', files=[('files', ('receipt.pdf', stream.getvalue(), 'application/pdf'))],
                                    data={'consent': 'true', 'request_key': 'retry-http'})
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()['batch_id']
        with patch.object(self.baseline, 'process', side_effect=RuntimeError('Synthetic processing failure')):
            self.assertEqual(self.client.post(f'/api/batches/{job}/run', json={'consent': True}).status_code, 200)
        self.client = TestClient(create_app(self.repo.db_path, pipeline_factory=factory), headers={'x-idp-request': '1'})
        self.login()
        summary = self.client.get(f'/api/batches/{job}').json()
        self.assertEqual(summary['counts']['failed'], 1)
        item = summary['items'][0]['id']
        self.assertEqual(self.client.post(f'/api/batch-items/{item}/retry').status_code, 200)
        self.assertEqual(self.client.get(f'/api/batches/{job}').json()['counts']['queued'], 1)
        self.assertEqual(self.client.post(f'/api/batches/{job}/run', json={'consent': True}).status_code, 200)
        summary = self.client.get(f'/api/batches/{job}').json()
        self.assertEqual(summary['counts']['failed'], 0)
        self.assertEqual(summary['counts']['completed'], 1)

    def employee(self, username, role):
        response=self.client.post('/api/users',json={'username':username,'password':self.password,'role':role,'departments':[]})
        self.assertEqual(response.status_code,200,response.text)
        client=TestClient(self.app,headers={'x-idp-request':'1'})
        self.login(username,client)
        return client,response.json()['id']

    def departmental_app(self):
        from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
        self.app=create_app(self.repo.db_path,pipeline_factory=lambda repo:AgenticDocumentPipeline(repo.db_path,
            baseline=self.baseline,llm=self.llm,session_token=repo.session_token))
        self.client=TestClient(self.app,headers={'x-idp-request':'1'})
        self.login()

    def employee_upload(self,client,kind,fields,name):
        self.llm.kind,self.llm.fields=kind,fields
        stream=io.BytesIO();pdf=canvas.Canvas(stream);pdf.drawString(50,750,name);pdf.save()
        response=client.post('/api/uploads/batch',files=[('files',(name+'.pdf',stream.getvalue(),'application/pdf'))],
            data={'consent':'true','request_key':name})
        self.assertEqual(response.status_code,200,response.text)
        job=response.json()['batch_id']
        run=client.post(f'/api/batches/{job}/run',json={'consent':True})
        self.assertEqual(run.status_code,200,run.text)
        summary=client.get(f'/api/batches/{job}').json()
        self.assertEqual(summary['counts']['failed'],0,summary)
        return summary['items'][0]['document_id'],job

    def test_employee_shared_po_matching_and_reference_permissions(self):
        self.departmental_app()
        procurement,_=self.employee('procurement-one','Procurement Reviewer')
        finance,_=self.employee('finance-one','Finance Reviewer')
        legal,_=self.employee('legal-one','Legal Reviewer')
        po,po_job=self.employee_upload(procurement,'purchase_order',{'po_number':'PO-TEAM','vendor':'Cedar','order_date':'2026-10-01','total':'INR 100.00'},'team-po')
        invoice,job=self.employee_upload(finance,'invoice',{'invoice_number':'INV-TEAM','seller':'Cedar','client':'Orbit','issue_date':'2026-10-01','total':'INR 100.00','po_reference':'PO-TEAM'},'team-invoice')
        detail=finance.get(f'/api/documents/{invoice}').json()
        self.assertEqual(detail['full_result']['cross_document_status'],'matched')
        self.assertEqual(detail['collaboration']['processed_by']['username'],'finance-one')
        self.assertEqual(detail['collaboration']['related_documents'][0]['id'],po)
        linked=finance.get(f'/api/documents/{po}').json()
        self.assertFalse(linked['collaboration']['can_review'])
        self.assertEqual(linked['collaboration']['processed_by']['username'],'procurement-one')
        payload={'expected_revision':linked['revision'],'confirmed':True,'reason':'Forbidden PO mutation','decision':'approved'}
        self.assertEqual(finance.post(f'/api/documents/{po}/decision',json=payload).status_code,403)
        self.assertEqual(legal.get(f'/api/documents/{invoice}').status_code,403)
        self.assertEqual(finance.get(f'/api/batches/{po_job}').status_code,403)
        self.assertEqual([row['id'] for row in finance.get('/api/batches').json()],[job])
        related=finance.get('/api/review?view=related').json()
        self.assertTrue(related['read_only'])
        self.assertIn(po,[row['id'] for row in related['rows']])
        self.assertNotIn(po,[row['id'] for row in finance.get('/api/review').json()['rows']])

    def test_two_employees_claim_concurrency_reassignment_and_persistence(self):
        one,one_id=self.employee('finance-one','Finance Reviewer')
        two,two_id=self.employee('finance-two','Finance Reviewer')
        self.assertEqual(one.get('/api/review?view=mine').json()['total'],0)
        before=one.get(f'/api/documents/{self.invoice}').json()
        body={'expected_revision':before['revision'],'confirmed':True,'reason':'Take responsibility','action':'claim'}
        self.assertEqual(one.post(f'/api/documents/{self.invoice}/case',json=body).status_code,200)
        visible=two.get(f'/api/documents/{self.invoice}').json()
        self.assertEqual(visible['case']['assignee'],f'user:{one_id}:finance-one')
        self.assertFalse(visible['collaboration']['can_review'])
        self.assertEqual(two.post(f'/api/documents/{self.invoice}/case',json=body).status_code,403)
        self.assertEqual(one.post(f'/api/documents/{self.invoice}/case',json=body).status_code,409)
        self.assertEqual(one.post('/api/logout').status_code,200)
        self.login('finance-one',one)
        self.assertEqual(one.get('/api/review?view=mine').json()['total'],1)
        self.assertEqual(two.get('/api/review?view=mine').json()['total'],0)
        changed={**body,'expected_revision':visible['revision'],'action':'assign','team':'Finance','assignee':f'user:{two_id}:finance-two'}
        self.assertEqual(self.client.post(f'/api/documents/{self.invoice}/case',json=changed).status_code,200)
        self.assertEqual(two.get('/api/review?view=mine').json()['total'],1)
        self.assertEqual(one.get('/api/review?view=mine').json()['total'],0)
        history=two.get(f'/api/documents/{self.invoice}').json()['events']
        self.assertEqual(history[-1]['actor'],f'user:{one_id}:finance-one')
        self.assertEqual(history[-1]['new_values']['actor_context']['departments'],['Finance'])

    def test_reconciliation_handoff_preserves_guard_and_department_visibility(self):
        self.departmental_app()
        finance,_=self.employee('finance-one','Finance Reviewer')
        procurement,_=self.employee('procurement-one','Procurement Reviewer')
        self.llm.kind='purchase_order'
        self.llm.fields={'po_number':'PO-MISMATCH','vendor':'Cedar','order_date':'2026-10-01','total':'INR 200.00'}
        baseline=self.baseline_result(None)
        baseline.ocr.full_text+='\nCorrect total: INR 100.00'
        with patch.object(self.baseline,'process',return_value=baseline):
            po,_=self.employee_upload(procurement,'purchase_order',self.llm.fields,'mismatch-po')
        invoice,_=self.employee_upload(finance,'invoice',{'invoice_number':'INV-MISMATCH','seller':'Cedar','client':'Orbit','issue_date':'2026-10-01','total':'INR 100.00','po_reference':'PO-MISMATCH'},'mismatch-invoice')
        before=finance.get(f'/api/documents/{invoice}').json()
        self.assertEqual(before['case']['team'],'Finance')
        body={'expected_revision':before['revision'],'reason':'Procurement investigate PO amount','confirmed':True,'action':'handoff','team':'Procurement'}
        self.assertEqual(finance.post(f'/api/documents/{invoice}/case',json={**body,'team':'Legal'}).status_code,400)
        self.assertEqual(finance.post(f'/api/documents/{invoice}/case',json=body).status_code,200)
        transferred=procurement.get(f'/api/documents/{invoice}').json()
        self.assertEqual(transferred['case']['team'],'Procurement')
        self.assertTrue(transferred['collaboration']['can_review'])
        self.assertFalse(finance.get(f'/api/documents/{invoice}').json()['collaboration']['can_review'])
        approval={'expected_revision':transferred['revision'],'reason':'Must not bypass mismatch','confirmed':True,'decision':'approved'}
        self.assertEqual(procurement.post(f'/api/documents/{invoice}/decision',json=approval).status_code,400)
        self.assertEqual(finance.post(f'/api/documents/{po}/case',json={**body,'expected_revision':self.repo.get_document(po)['revision']}).status_code,403)
        self.assertEqual(transferred['events'][0]['event_type'],'handoff')
        self.assertEqual(transferred['events'][0]['previous_values']['team'],'Finance')
        back={**body,'expected_revision':transferred['revision'],'team':'Finance'}
        self.assertEqual(procurement.post(f'/api/documents/{invoice}/case',json=back).status_code,400)
        po_state=procurement.get(f'/api/documents/{po}').json()
        correction={'expected_revision':po_state['revision'],'confirmed':True,'reason':'Correct total supported by original OCR','changes':{'total':'INR 100.00'},'evidence':{'total':'Correct total: INR 100.00'}}
        self.assertEqual(procurement.post(f'/api/documents/{po}/correction',json=correction).status_code,200)
        changed=procurement.get(f'/api/documents/{invoice}').json()
        self.assertEqual(changed['full_result']['cross_document_status'],'incomplete')
        self.assertEqual(changed['review_decision'],'needs_correction')
        back['expected_revision']=changed['revision']
        self.assertEqual(procurement.post(f'/api/documents/{invoice}/case',json=back).status_code,200)
        ready=finance.get(f'/api/documents/{invoice}').json()
        self.assertEqual(ready['case']['team'],'Finance')
        self.assertEqual(ready['full_result']['cross_document_status'],'matched')
        self.assertEqual(ready['review_decision'],'pending')
        self.assertFalse(procurement.get(f'/api/documents/{invoice}').json()['collaboration']['can_review'])


    def test_document_reviewer_corrects_supported_evidence_and_returns_to_finance(self):
        self.departmental_app()
        finance,_=self.employee('finance-one','Finance Reviewer')
        reviewer,_=self.employee('document-one','Document Reviewer')
        self.llm.kind='invoice'
        self.llm.fields={'invoice_number':'INV-FIX','seller':'Cedar','client':'Orbit','issue_date':'2026-10-01'}
        from types import SimpleNamespace
        baseline=self.baseline_result(None)
        baseline.ocr.full_text+='\nTotal: INR 100.00'
        with patch.object(self.baseline,'process',return_value=baseline):
            invoice,_=self.employee_upload(finance,'invoice',self.llm.fields,'incomplete-invoice')
        doc=reviewer.get(f'/api/documents/{invoice}').json()
        self.assertEqual(doc['case']['team'],'Document Review')
        self.assertFalse(finance.get(f'/api/documents/{invoice}').json()['collaboration']['can_review'])
        body={'expected_revision':doc['revision'],'confirmed':True,'reason':'Recover missing total from original OCR','changes':{'total':'INR 100.00'},'evidence':{'total':'Total: INR 100.00'}}
        self.assertEqual(reviewer.post(f'/api/documents/{invoice}/correction',json=body).status_code,200)
        corrected=finance.get(f'/api/documents/{invoice}').json()
        self.assertEqual(corrected['case']['team'],'Finance')
        self.assertTrue(corrected['collaboration']['can_review'])
        self.assertEqual(corrected['review_decision'],'pending')
        returned_reference=reviewer.get(f'/api/documents/{invoice}')
        self.assertEqual(returned_reference.status_code,200)
        self.assertFalse(returned_reference.json()['collaboration']['can_review'])
        self.assertIsNone(self.repo.get_document(invoice)['full_result'].get('human_evidence_errors',{}).get('total'))
        self.assertNotIn('total',__import__('json').loads(corrected['versions'][0]['original_state'])['extracted_fields'])

    def test_employee_credentials_reset_deactivation_and_no_role_self_assignment(self):
        employee,user_id=self.employee('finance-one','Finance Reviewer')
        revision=next(u['revision'] for u in self.client.get('/api/users').json()['users'] if u['id']==user_id)
        new_password=secrets.token_urlsafe(24)
        reset={'expected_revision':revision,'new_password':new_password,'confirmed':True}
        self.assertEqual(employee.post(f'/api/users/{user_id}/credentials',json=reset).status_code,403)
        self.assertEqual(self.client.post(f'/api/users/{user_id}/credentials',json=reset).status_code,200)
        self.assertEqual(employee.get('/api/session').status_code,401)
        self.assertEqual(employee.post('/api/login',json={'username':'finance-one','password':self.password}).status_code,401)
        self.assertEqual(employee.post('/api/login',json={'username':'finance-one','password':new_password}).status_code,200)
        self.assertEqual(employee.post('/api/users',json={'username':'elevated','password':new_password,'role':'Administrator','departments':[]}).status_code,403)
        revision+=1
        self.assertEqual(self.client.post(f'/api/users/{user_id}',json={'expected_revision':revision,'role':'Finance Reviewer','departments':[],'active':False,'confirmed':True}).status_code,200)
        self.assertEqual(employee.get('/api/session').status_code,401)
        with self.repo.connect() as db:
            events=[str(tuple(row)) for row in db.execute('SELECT * FROM security_events')]
            self.assertNotIn(new_password,' '.join(events))
            self.assertTrue(any('credentials_reset' in event for event in events))

    def test_new_employee_dashboard_and_returning_work_scope(self):
        expense,_=self.employee('expense-one','Expense Reviewer')
        overview=expense.get('/api/overview').json()
        self.assertEqual(overview['employee_work']['department_cases'],0)
        self.assertGreater(len(self.repo.list_documents()),0)
        self.assertEqual(overview['employee_work']['assigned_to_me'],0)
        self.assertEqual(overview['employee_work']['previous_sign_in'],None)
        self.assertEqual(expense.post('/api/logout').status_code,200)
        self.login('expense-one',expense)
        overview=expense.get('/api/overview').json()
        self.assertIsNotNone(overview['employee_work']['previous_sign_in'])
        self.assertEqual(overview['employee_work']['recent_changes'],[])
        self.assertEqual(expense.get('/api/review?view=mine').json()['total'],0)

    def test_departmental_intake_cannot_probe_private_duplicates_or_force_reprocess(self):
        self.departmental_app()
        finance,_=self.employee('finance-one','Finance Reviewer')
        from idp.storage.repository import DocumentRepository
        from idp.security.auth import AccessDenied
        token=finance.cookies.get('idp_session')
        repo=DocumentRepository(self.repo.db_path,session_token=token)
        with self.assertRaises(AccessDenied): repo.find_by_hash(self.repo.get_document(self.contract)['file_hash'])
        stream=io.BytesIO();pdf=canvas.Canvas(stream);pdf.drawString(50,750,'Only administrator may force');pdf.save()
        denied=finance.post('/api/uploads/batch',files=[('files',('force.pdf',stream.getvalue(),'application/pdf'))],data={'consent':'true','force':'true','request_key':'unauthorized-force'})
        self.assertEqual(denied.status_code,403)
        self.assertEqual(finance.get('/api/policies').status_code,403)

    def test_employee_department_change_revokes_old_work_and_owned_jobs(self):
        self.departmental_app()
        finance,user_id=self.employee('changing-employee','Finance Reviewer')
        invoice,job=self.employee_upload(finance,'invoice',{'invoice_number':'INV-CHANGE','seller':'Cedar','client':'Orbit','issue_date':'2026-10-01','total':'INR 100.00'},'role-change-invoice')
        revision=next(user['revision'] for user in self.client.get('/api/users').json()['users'] if user['id']==user_id)
        self.assertEqual(self.client.post(f'/api/users/{user_id}',json={'expected_revision':revision,'role':'Legal Reviewer','departments':['Finance'],'active':True,'confirmed':True}).status_code,200)
        self.assertEqual(finance.get('/api/session').status_code,401)
        self.login('changing-employee',finance)
        self.assertEqual(finance.get('/api/session').json()['departments'],['Legal'])
        self.assertEqual(finance.get(f'/api/documents/{invoice}').status_code,403)
        self.assertEqual(finance.get(f'/api/batches/{job}').status_code,403)
        self.assertEqual(finance.get('/api/batches').json(),[])
        self.assertEqual(finance.get('/api/review?view=mine').json()['total'],0)

    def test_wrong_department_intake_cannot_persist_or_disclose_results(self):
        self.departmental_app()
        finance,_=self.employee('finance-one','Finance Reviewer')
        self.llm.kind='contract'
        self.llm.fields={'contract_title':'Confidential Legal Fixture','party_a':'Cedar','party_b':'Orbit','effective_date':'2026-10-01'}
        stream=io.BytesIO();pdf=canvas.Canvas(stream);pdf.drawString(50,750,'Wrong department synthetic file');pdf.save()
        before=len(self.repo.list_documents())
        response=finance.post('/api/uploads/batch',files=[('files',('wrong.pdf',stream.getvalue(),'application/pdf'))],data={'consent':'true','request_key':'wrong-type'})
        self.assertEqual(response.status_code,200)
        job=response.json()['batch_id']
        self.assertEqual(finance.post(f'/api/batches/{job}/run',json={'consent':True}).status_code,200)
        summary=finance.get(f'/api/batches/{job}').json()
        self.assertEqual(summary['counts']['failed'],1)
        self.assertIsNone(summary['items'][0]['document_id'])
        self.assertNotIn('Confidential Legal Fixture',str(summary))
        self.assertEqual(len(self.repo.list_documents()),before)

    def test_ui_setup_endpoint_requires_local_credential_and_disables_after_success(self):
        from idp.storage.repository import DocumentRepository
        from idp.security import INTERNAL
        path=self.root/'first_install.db';app=create_app(path)
        client=TestClient(app,headers={'x-idp-request':'1'})
        from idp.security.auth import REQUEST_DEPARTMENTS
        self.assertEqual(client.get('/api/onboarding').json(),{'setup_required':True,'setup_authorized':False,'requested_departments':list(REQUEST_DEPARTMENTS)})
        body={'username':'initial-admin','password':self.password,'setup_token':'x'*43}
        self.assertEqual(client.post('/api/setup',json=body).status_code,401)
        self.assertEqual(client.post('/api/registrations',json={'username':'early-employee','password':self.password}).status_code,400)
        repo=DocumentRepository(path,_capability=INTERNAL)
        token=AuthService(repo).authorize_setup(capability=INTERNAL)
        self.assertTrue(client.get('/api/onboarding').json()['setup_authorized'])
        for malformed in ({**body,'setup_token':token,'unexpected':token},
                          {**body,'setup_token':token,'password':self.password*20},
                          {**body,'setup_token':'short-private-value'}):
            invalid=client.post('/api/setup',json=malformed)
            self.assertEqual(invalid.status_code,422)
            for secret in (token,self.password,'short-private-value'):
                self.assertNotIn(secret,invalid.text)
        body['setup_token']=token
        response=client.post('/api/setup',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn(token,response.text+client.get('/api/onboarding').text)
        self.assertEqual(client.post('/api/setup',json=body).status_code,401)
        self.assertEqual(client.post('/api/login',json={'username':'initial-admin','password':self.password}).status_code,200)
        self.assertEqual(client.get('/api/session').json()['role'],'Administrator')

    def test_pending_http_registration_has_no_access_until_admin_approval(self):
        pending=TestClient(self.app,headers={'x-idp-request':'1'})
        body={'username':'pending-finance','password':self.password}
        response=pending.post('/api/registrations',json=body)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),pending.post('/api/registrations',json=body).json())
        self.assertEqual(response.json(),pending.post('/api/registrations',json={'username':'web-admin','password':self.password}).json())
        self.assertEqual(pending.post('/api/registrations',json={**body,'role':'Administrator','departments':['Legal']}).status_code,422)
        self.assertEqual(pending.post('/api/login',json=body).status_code,401)
        for route in ('/api/session','/api/documents','/api/overview','/api/analytics','/api/review','/api/users','/api/batches','/api/audit'):
            self.assertEqual(pending.get(route).status_code,401,route)
        self.assertEqual(pending.post('/api/downloads',json={'kind':'document_json','resource':{'document_id':self.invoice}}).status_code,401)
        request=self.client.get('/api/users').json()['registration_requests'][0]
        self.assertNotIn('password_hash',request)
        approval={'expected_revision':request['revision'],'role':'Finance Reviewer','departments':['Legal'],'confirmed':True}
        self.assertEqual(pending.post(f"/api/registrations/{request['id']}/approve",json=approval).status_code,401)
        self.assertEqual(self.client.post(f"/api/registrations/{request['id']}/approve",json=approval).status_code,200)
        self.assertEqual(self.client.post(f"/api/registrations/{request['id']}/approve",json=approval).status_code,400)
        self.assertEqual(pending.post('/api/login',json=body).status_code,200)
        self.assertEqual(pending.get('/api/session').json()['departments'],['Finance'])
        self.assertEqual(pending.get(f'/api/documents/{self.invoice}').status_code,200)
        self.assertEqual(pending.get(f'/api/documents/{self.contract}').status_code,403)
        self.assertEqual(pending.post('/api/logout').status_code,200)
        self.assertEqual(pending.post('/api/login',json=body).status_code,200)
        self.assertEqual(pending.get(f'/api/documents/{self.invoice}').status_code,200)

    def test_registration_approval_requires_administrator_and_current_revision(self):
        anonymous=TestClient(self.app,headers={'x-idp-request':'1'})
        anonymous.post('/api/registrations',json={'username':'request-one','password':self.password})
        request=self.client.get('/api/users').json()['registration_requests'][0]
        approval={'expected_revision':99,'role':'Legal Reviewer','departments':[],'confirmed':True}
        self.assertEqual(self.client.post(f"/api/registrations/{request['id']}/approve",json=approval).status_code,400)
        finance=TestClient(self.app,headers={'x-idp-request':'1'});self.login('web-finance',finance)
        approval['expected_revision']=request['revision']
        self.assertEqual(finance.post(f"/api/registrations/{request['id']}/approve",json=approval).status_code,403)
        approval['confirmed']=False
        self.assertEqual(self.client.post(f"/api/registrations/{request['id']}/approve",json=approval).status_code,422)

    def test_concurrent_http_bootstrap_only_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from idp.storage.repository import DocumentRepository
        from idp.security import INTERNAL
        path=self.root/'concurrent_http_setup.db'
        repo=DocumentRepository(path,_capability=INTERNAL)
        token=AuthService(repo).authorize_setup(capability=INTERNAL)
        app=create_app(path)
        def submit(index):
            client=TestClient(app,headers={'x-idp-request':'1'})
            return client.post('/api/setup',json={'username':f'first-admin-{index}','password':self.password,'setup_token':token}).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses=list(executor.map(submit,range(2)))
        self.assertEqual(statuses.count(200),1,statuses)
        with repo.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],1)

    def test_requested_department_override_and_returning_employee(self):
        applicant=TestClient(self.app,headers={'x-idp-request':'1'})
        credentials={'username':'department-applicant','password':self.password}
        self.assertEqual(applicant.post('/api/registrations',json={**credentials,'requested_department':'Finance'}).status_code,200)
        self.assertEqual(applicant.post('/api/login',json=credentials).status_code,401)
        request=self.client.get('/api/users').json()['registration_requests'][0]
        self.assertEqual(request['requested_department'],'Finance')
        self.assertEqual(self.client.get('/api/overview').json()['pending_registrations'],1)
        approved=self.client.post(f"/api/registrations/{request['id']}/approve",json={
            'expected_revision':0,'role':'Legal Reviewer','departments':['Finance'],'confirmed':True})
        self.assertEqual(approved.status_code,200)
        account=next(user for user in self.client.get('/api/users').json()['users'] if user['id']==approved.json()['id'])
        self.assertEqual(account['requested_department'],'Finance')
        self.assertEqual(account['role'],'Legal Reviewer')
        self.assertEqual(account['departments'],'["Legal"]')
        self.assertNotIn('password_hash',account)
        self.assertEqual(applicant.post('/api/login',json=credentials).status_code,200)
        session=applicant.get('/api/session').json()
        self.assertEqual(session['departments'],['Legal'])
        self.assertNotIn('users',session['permissions'])
        self.assertNotIn('pending_registrations',applicant.get('/api/overview').json())
        self.assertEqual(applicant.get(f'/api/documents/{self.contract}').status_code,200)
        self.assertEqual(applicant.get(f'/api/documents/{self.invoice}').status_code,403)
        self.assertEqual(applicant.post(f"/api/users/{approved.json()['id']}",json={
            'expected_revision':0,'role':'Administrator','departments':['Finance'],'active':True,'confirmed':True}).status_code,403)
        applicant.post('/api/logout')
        restarted=TestClient(create_app(self.repo.db_path),headers={'x-idp-request':'1'})
        self.assertEqual(restarted.post('/api/login',json=credentials).status_code,200)
        self.assertEqual(restarted.get('/api/session').json()['departments'],['Legal'])
        self.assertEqual(restarted.get(f'/api/documents/{self.contract}').status_code,200)

    def test_department_request_cannot_spoof_authority_and_decline_is_guarded(self):
        applicant=TestClient(self.app,headers={'x-idp-request':'1'})
        body={'username':'decline-applicant','password':self.password,'requested_department':'Legal'}
        for extra in ({'role':'Administrator'},{'departments':['Finance']},{'user_id':1},{'requested_department':'Administrator'}):
            response=applicant.post('/api/registrations',json={**body,**extra})
            self.assertIn(response.status_code,(400,422))
            self.assertNotIn(self.password,response.text)
        self.assertEqual(applicant.post('/api/registrations',json=body).status_code,200)
        request=self.client.get('/api/users').json()['registration_requests'][0]
        path=f"/api/registrations/{request['id']}/reject"
        payload={'expected_revision':0,'confirmed':True}
        self.assertEqual(applicant.post(path,json=payload).status_code,401)
        finance=TestClient(self.app,headers={'x-idp-request':'1'});self.login('web-finance',finance)
        self.assertEqual(finance.post(path,json=payload).status_code,403)
        self.assertEqual(self.client.post(path,json={**payload,'confirmed':False}).status_code,422)
        self.assertEqual(self.client.post(path,json={**payload,'expected_revision':99}).status_code,400)
        self.assertEqual(self.client.post(path,json=payload).status_code,200)
        self.assertEqual(self.client.get('/api/users').json()['registration_requests'],[])
        self.assertEqual(applicant.post('/api/login',json={'username':body['username'],'password':self.password}).status_code,401)
        with self.repo.connect() as db:
            event=db.execute("SELECT * FROM security_events WHERE event_type='registration_declined'").fetchone()
            self.assertEqual(event['user_id'],AuthService(self.repo).resolve(self.client.cookies['idp_session'])['id'])

    def test_all_eight_roles_keep_server_side_destinations_and_mutation_guards(self):
        from idp.security.access import PERMISSIONS
        for index,(role,permissions) in enumerate(PERMISSIONS.items()):
            with self.subTest(role=role):
                username=f'permission-role-{index}'
                AuthService(self.repo).create_user(username,self.password,role,['Finance'])
                employee=TestClient(self.app,headers={'x-idp-request':'1'});self.login(username,employee)
                self.assertEqual(set(employee.get('/api/session').json()['permissions']),permissions)
                for route,permission in (('/api/overview','analytics'),('/api/documents','documents'),('/api/review','review'),('/api/users','users'),('/api/audit','security_audit')):
                    self.assertEqual(employee.get(route).status_code,200 if permission in permissions else 403,(role,route))
                if role!='Administrator':
                    self.assertEqual(employee.post('/api/users',json={'username':'forged-user','password':self.password,'role':'Administrator','departments':[]}).status_code,403)
                if role not in ('Administrator','Legal Reviewer'):
                    self.assertEqual(employee.post(f'/api/documents/{self.contract}/decision',json={
                        'expected_revision':0,'reason':'Attempt outside department','confirmed':True,'decision':'rejected'}).status_code,403)

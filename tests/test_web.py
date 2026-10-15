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

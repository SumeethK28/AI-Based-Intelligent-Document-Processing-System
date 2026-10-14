"""Authenticated single-use download delivery; no public Streamlit file/media storage."""
import json
import secrets
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from idp.security.auth import AuthService, AccessDenied, digest
from idp.storage.repository import DocumentRepository


class DownloadService:
    def __init__(self,repository,*,clock=time.time):
        self.repository=repository
        self.clock=clock

    def grant(self,kind,resource):
        repo=self.repository
        principal=repo.require('source' if kind=='source' else 'analytics_export' if kind=='analytics_json' else 'export')
        if repo.internal: raise ValueError('Downloads require an authenticated session.')
        self.authorize(repo,kind,resource)
        token=secrets.token_urlsafe(32)
        with repo._connect() as db:
            db.execute('INSERT INTO download_grants VALUES(?,?,?,?,?,0)',(digest(token),repo.session_hash or digest(repo.session_token),kind,json.dumps(resource),self.clock()+30))
            AuthService(repo).event('download_granted','allowed',kind,principal['id'],db)
        return token

    @staticmethod
    def authorize(repo,kind,resource):
        if kind=='source':
            from idp.batch.service import BatchService
            with repo._connect() as db: item=db.execute('SELECT * FROM batch_items WHERE id=?',(resource.get('item_id'),)).fetchone()
            if not item: raise AccessDenied('Source is unavailable.')
            BatchService(repo).source(dict(item))
        elif kind=='document_json': repo.access.document(resource.get('document_id'),'export')
        elif kind=='analytics_json': repo.require('analytics_export')
        elif kind in {'filtered_json','filtered_csv'}: repo.require('export')
        elif kind in {'batch_json','batch_csv'}: repo.require('batches'); repo.require('export')
        else: raise AccessDenied('Unsupported download operation.')

    def redeem(self,token):
        if not isinstance(token,str) or len(token)>128: raise AccessDenied('Download unavailable.')
        with self.repository._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            grant=db.execute('SELECT * FROM download_grants WHERE grant_hash=?',(digest(token),)).fetchone()
            if not grant or grant['used'] or self.clock()>=grant['expires_at']: raise AccessDenied('Download expired or already used.')
            db.execute('UPDATE download_grants SET used=1 WHERE grant_hash=?',(digest(token),))
            grant=dict(grant)
        repo=DocumentRepository(self.repository.db_path,_session_hash=grant['session_hash'])
        principal=AuthService(repo,clock=self.clock).resolve_hash(grant['session_hash'])
        resource=json.loads(grant['resource']); kind=grant['kind']
        self.authorize(repo,kind,resource)
        if kind=='source':
            from idp.batch.service import BatchService
            with repo._connect() as db: item=dict(db.execute('SELECT * FROM batch_items WHERE id=?',(resource['item_id'],)).fetchone())
            path=BatchService(repo).source(item)
            data=path.read_bytes(); filename=item['filename']; mime='application/pdf' if path.suffix=='.pdf' else 'image/png' if path.suffix=='.png' else 'image/jpeg'
        elif kind=='document_json':
            data=json.dumps(repo.get_document(resource['document_id'])['full_result'],indent=2).encode(); filename='document.json'; mime='application/json'
        else:
            from idp.storage.operations import OperationsQueries,DocumentFilters
            from idp.batch.service import BatchService
            values=resource.get('filters',{})
            for key in ('start_date','end_date'):
                if values.get(key): values[key]=date.fromisoformat(values[key])
            filters=DocumentFilters(**values)
            if kind=='analytics_json':
                from idp.storage.intelligence import IntelligenceQueries
                payload=IntelligenceQueries(repo).report(filters)
            elif kind.startswith('batch_'): payload=BatchService(repo).summary(resource['batch_id'])
            else: payload=OperationsQueries(repo).export(filters)
            if kind.endswith('csv'):
                rows=payload['items'] if isinstance(payload,dict) else [{**row,'extracted_data':json.dumps(row['extracted_data'])} for row in payload]
                data=BatchService.csv(rows).encode(); filename='export.csv'; mime='text/csv'
            else: data=json.dumps(payload,indent=2).encode(); filename='export.json'; mime='application/json'
        AuthService(repo).event('sensitive_download','allowed',kind,principal['id'])
        return data,filename,mime


_SERVERS={}
_LOCK=threading.Lock()


def start_download_server(database_path,port=8767):
    """One server per local app instance. Never bind externally or log bearer URLs."""
    key=str(database_path)
    with _LOCK:
        if key in _SERVERS: return _SERVERS[key]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                try:
                    parsed=urlparse(self.path)
                    if parsed.path!='/download': raise AccessDenied('Unavailable')
                    token=parse_qs(parsed.query).get('grant',[''])[0]
                    service=DownloadService(DocumentRepository(database_path))
                    data,name,mime=service.redeem(token)
                    name=''.join(char for char in name if char.isalnum() or char in '._- ')[:120] or 'document'
                    self.send_response(200)
                    self.send_header('Content-Type',mime)
                    self.send_header('Content-Disposition',f'attachment; filename="{name}"')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('Referrer-Policy','no-referrer')
                    self.send_header('X-Content-Type-Options','nosniff')
                    self.send_header('Content-Length',str(len(data)))
                    self.end_headers(); self.wfile.write(data)
                except Exception:
                    try: AuthService(DocumentRepository(database_path)).event('download_denied','denied','download')
                    except Exception: pass
                    self.send_response(403); self.send_header('Cache-Control','no-store'); self.end_headers()
                    self.wfile.write(b'Download unavailable. Sign in and request a fresh authorized download.')
        server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        _SERVERS[key]=server
        return server

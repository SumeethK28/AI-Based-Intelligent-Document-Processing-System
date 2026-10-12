"""Persistent, idempotent batches and serial crash-recoverable local worker."""
import csv
import io
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from idp.batch.ingestion import preview, inspect_file
from idp.utils.exports import spreadsheet_safe
from idp.utils.money import parse_money

TERMINAL = {'completed','duplicate','failed','review_required'}


@contextmanager
def worker_lock(path):
    """OS lock is released on death; SQLite persists work, not a session/thread."""
    lock = Path(str(Path(path).resolve()) + '.worker.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+b') as handle:
        if lock.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Another local worker is processing this database. Refresh to monitor progress.') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def safe_failure(error):
    # Never persist provider exception strings, keys, response bodies or local paths.
    status = getattr(error, 'status_code', None)
    if status == 429:
        return 'rate_limit', 'Provider quota reached after bounded retries. Retry later.'
    if status in {401,403}:
        return 'credentials', 'Provider authorization failed. Check local configuration before retrying.'
    if status == 400:
        return 'request', 'Provider rejected the request. Check document support and configuration.'
    if status and status >= 500 or isinstance(error, (TimeoutError, ConnectionError)) or type(error).__name__ in {'APIConnectionError','APITimeoutError'}:
        return 'transient', 'Provider or connection temporarily unavailable. Retry later.'
    if isinstance(error, (ValueError, FileNotFoundError)):
        return 'document', 'Source is unavailable, damaged, changed or could not be processed. Check retained source.'
    return 'processing', 'Document processing failed. Other items continue; inspect the source and retry.'


class BatchService:
    def __init__(self, repository):
        self.repository = repository
        self.root = (repository.db_path.resolve().parent / 'batch_sources').resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            self.root.chmod(0o700)

    def submit(self, files, *, request_key, name='Document batch', description='', force=False):
        if not request_key or len(request_key) > 128:
            raise ValueError('A valid submission identifier is required.')
        with self.repository.connect() as db:
            prior = db.execute('SELECT id FROM batch_jobs WHERE request_key=?',(request_key,)).fetchone()
        if prior:
            return prior['id']
        rows, accepted = preview(files, self.repository)
        if not accepted:
            raise ValueError('No supported documents were accepted.')
        batch_id = uuid.uuid4().hex
        now = self.repository.timestamp()
        retained = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        paths = []
        # Inputs are durable before DB submission. Names never determine storage paths.
        for info, data in accepted:
            path = self.root / (uuid.uuid4().hex + info['extension'])
            with path.open('xb') as target:
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            if os.name != 'nt':
                path.chmod(0o600)
            paths.append((info, path))
        with self.repository.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT id FROM batch_jobs WHERE request_key=?',(request_key,)).fetchone()
            if prior:
                # Only our unreferenced fresh files; never existing retained sources.
                for _, path in paths:
                    path.unlink()
                return prior['id']
            db.execute('INSERT INTO batch_jobs(id,request_key,name,description,created_at) VALUES(?,?,?,?,?)',
                       (batch_id,request_key,name.strip()[:200] or 'Document batch',description[:2000],now))
            for info, path in paths:
                db.execute('''INSERT INTO batch_items(batch_id,filename,file_hash,source_path,size_bytes,pages,force_reprocess,retain_until)
                    VALUES(?,?,?,?,?,?,?,?)''', (batch_id,info['filename'],info['file_hash'],str(path),info['size_bytes'],info['pages'],int(force),retained))
        return batch_id

    def history(self):
        with self.repository.connect() as db:
            return [dict(row) for row in db.execute('''SELECT b.*,count(i.id) AS items,
                sum(i.state='queued') AS queued,sum(i.state='processing') AS processing,
                sum(i.state='failed') AS failed FROM batch_jobs b JOIN batch_items i ON i.batch_id=b.id
                GROUP BY b.id ORDER BY b.created_at DESC''')]

    def items(self, batch_id):
        with self.repository.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM batch_items WHERE batch_id=? ORDER BY id',(batch_id,))]

    def source(self, item):
        original = Path(item['source_path'])
        path = original.resolve()
        if path.parent != self.root or original.is_symlink() or not path.is_file():
            raise FileNotFoundError('Retained source unavailable')
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Retained source exceeds size limit')
        return path

    def attempts(self, item_id):
        with self.repository.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM batch_attempts WHERE item_id=? ORDER BY id',(item_id,))]

    def retry(self, item_id):
        with worker_lock(self.repository.db_path), self.repository.connect() as db:
            row = db.execute('SELECT * FROM batch_items WHERE id=?',(item_id,)).fetchone()
            if not row or row['state'] != 'failed':
                raise ValueError('Only failed items can be retried.')
            if row['attempts'] >= 5:
                raise ValueError('This item reached the five-attempt limit. Investigate before making a new submission.')
            self.source(row)
            db.execute("UPDATE batch_items SET state='queued',generation=generation+1,error_category=NULL,safe_error=NULL,completed_at=NULL WHERE id=?",(item_id,))
            db.execute('UPDATE batch_jobs SET reconciled_at=NULL WHERE id=?',(row['batch_id'],))

    def run(self, pipeline_factory, batch_id=None, *, max_items=50, progress=None):
        count = 0
        with worker_lock(self.repository.db_path):
            with self.repository.connect() as db:
                # A free OS lock proves previous worker is gone; retain interrupted attempt.
                db.execute("UPDATE batch_attempts SET state='interrupted',completed_at=? WHERE state='processing'",(self.repository.timestamp(),))
                db.execute("UPDATE batch_items SET state='queued' WHERE state='processing'")
            pipeline = None
            while count < max_items:
                with self.repository.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute("SELECT * FROM batch_items WHERE state='queued'" + (' AND batch_id=?' if batch_id else '') + ' ORDER BY id LIMIT 1', (batch_id,) if batch_id else ()).fetchone()
                    if not row:
                        break
                    item = dict(row)
                    started = self.repository.timestamp()
                    db.execute("UPDATE batch_items SET state='processing',attempts=attempts+1,started_at=? WHERE id=?",(started,item['id']))
                    attempt_id = db.execute("INSERT INTO batch_attempts(item_id,attempt,started_at,state) VALUES(?,?,?,'processing')",(item['id'],item['attempts']+1,started)).lastrowid
                if progress:
                    progress(item, 'processing')
                tick = time.perf_counter()
                try:
                    path = self.source(item)
                    data = path.read_bytes()
                    info = inspect_file(item['filename'],data)
                    if info['file_hash'] != item['file_hash']:
                        raise ValueError('Source changed')
                    if pipeline is None:
                        pipeline = pipeline_factory()
                    result = pipeline.process(path, original_filename=item['filename'],force_reprocess=bool(item['force_reprocess']),operation_key=f"batch:{item['id']}:{item['generation']}")
                    state = result['state']
                    outcome = 'duplicate' if result['duplicate'] else 'review_required' if state.get('workflow_status') != 'pending_department_review' else 'completed'
                    category = message = None
                except Exception as error:
                    outcome = 'failed'
                    category, message = safe_failure(error)
                    result = None
                duration = time.perf_counter() - tick
                with self.repository.connect() as db:
                    completed = self.repository.timestamp()
                    db.execute('''UPDATE batch_items SET state=?,completed_at=?,document_id=?,run_id=?,error_category=?,safe_error=?,duration_seconds=?,result_snapshot=? WHERE id=?''',
                        (outcome,completed,result['document_id'] if result else None,result['run_id'] if result else None,category,message,duration,json.dumps(result['state']) if result else None,item['id']))
                    db.execute('UPDATE batch_attempts SET state=?,completed_at=?,error_category=?,safe_error=?,duration_seconds=? WHERE id=?',(outcome,completed,category,message,duration,attempt_id))
                count += 1
                if progress:
                    progress(item, outcome)
            jobs = [batch_id] if batch_id else [job['id'] for job in self.history()]
            for job in jobs:
                self.reconcile(job)
        return count

    def reconcile(self, batch_id):
        """Deterministic post-batch PO recheck: no OCR/model call, no new run."""
        items = self.items(batch_id)
        if any(item['state'] not in TERMINAL for item in items):
            return
        with self.repository.connect() as db:
            job = db.execute('SELECT reconciled_at FROM batch_jobs WHERE id=?',(batch_id,)).fetchone()
        if not job or job['reconciled_at']:
            return
        from idp.agents.validation_agent import ValidationAgent
        from idp.agents.anomaly_agent import AnomalyDetectionAgent
        from idp.agents.cross_document_agent import CrossDocumentAgent
        from idp.agents.routing_agent import WorkflowRoutingAgent
        seen = set()
        for item in items:
            if not item['document_id'] or item['document_id'] in seen:
                continue
            seen.add(item['document_id'])
            document = self.repository.get_document(item['document_id'])
            if document['review_decision'] in {'rejected','needs_correction','escalated'}:
                continue  # Batch reconciliation cannot overturn an explicit human restriction.
            state = document['full_result']
            if state.get('document_type') != 'invoice' or not state.get('extracted_fields',{}).get('po_reference'):
                continue
            state = dict(state)
            previous_issues = state.get('cross_document_issues',[])
            other_anomalies = [value for value in state.get('anomalies',[]) if value not in previous_issues]
            state.update(ValidationAgent().run(state))
            state.update(AnomalyDetectionAgent().run(state))
            state['anomalies'] += [value for value in other_anomalies if value not in state['anomalies']]
            levels = {value.get('severity','low') for value in state['anomalies']}
            if document['full_result'].get('risk_level') == 'high':
                levels.add('high')  # Resolving a PO is not authorization to clear other high-risk signals.
            state['risk_level'] = 'high' if 'high' in levels else 'medium' if 'medium' in levels else 'low'
            state.update(CrossDocumentAgent(self.repository).run(state))
            state.update(WorkflowRoutingAgent().run(state))
            if all(state.get(key)==document['full_result'].get(key) for key in ('cross_document_status','cross_document_issues','matched_document_id','workflow_status')):
                continue
            encoded = json.dumps(state)
            # Do not reset review decisions or repeat processing-run side effects.
            with self.repository.connect() as db:
                changed = db.execute('UPDATE documents SET full_result=?,workflow_status=?,assigned_department=?,updated_at=? WHERE id=? AND full_result=?',
                    (encoded,state['workflow_status'],state['assigned_department'],self.repository.timestamp(),document['id'],json.dumps(document['full_result'],ensure_ascii=False)))
                if not changed.rowcount:
                    continue
                from idp.review.service import ReviewService
                ReviewService(self.repository).event(db,document,'batch_reconciliation',
                    {'cross_document_status':document['full_result'].get('cross_document_status'),'workflow_status':document['workflow_status']},
                    {'cross_document_status':state['cross_document_status'],'workflow_status':state['workflow_status']},
                    'system:batch-worker','Post-batch purchase-order reconciliation refreshed deterministic checks.',state=state)
                db.execute('''UPDATE batch_items SET result_snapshot=?,state=CASE WHEN state='duplicate' THEN state ELSE ? END
                    WHERE batch_id=? AND document_id=? AND state!='failed' ''',
                    (encoded,'completed' if state['workflow_status']=='pending_department_review' else 'review_required',batch_id,document['id']))
        with self.repository.connect() as db:
            db.execute('UPDATE batch_jobs SET reconciled_at=? WHERE id=?',(self.repository.timestamp(),batch_id))

    def summary(self, batch_id):
        items = self.items(batch_id)
        rows, unique, totals = [], {}, {}
        for item in items:
            state = json.loads(item['result_snapshot']) if item['result_snapshot'] else {}
            rows.append({**{key:item[key] for key in ('id','filename','state','attempts','document_id','run_id','error_category','safe_error','duration_seconds')},
                         'document_type':state.get('document_type'),'validation_passed':state.get('validation_passed'),
                         'cross_document_status':state.get('cross_document_status'),'department':state.get('assigned_department')})
            if item['document_id']:
                unique[item['document_id']] = state
        for state in unique.values():
            if state.get('document_type') != 'invoice':
                continue
            amount = parse_money(state.get('extracted_fields',{}).get('total'))
            if amount:
                key = (amount.currency or 'Unspecified currency','flagged' if state.get('requires_review') or not state.get('validation_passed') or state.get('workflow_status')!='pending_department_review' else 'preliminary checks passed')
                totals[key] = totals.get(key,0) + amount.amount
        distributions = {}
        for key in ('document_type','validation_passed','cross_document_status','assigned_department'):
            distribution = {}
            for state in unique.values():
                value = str(state.get(key,'unknown'))
                distribution[value] = distribution.get(value,0) + 1
            distributions[key] = distribution
        return {'batch_id':batch_id,'items':rows,'counts':{key:sum(item['state']==key for item in items) for key in ('queued','processing','completed','duplicate','failed','review_required')},
                'unique_documents':len(unique),'distributions':distributions,
                'measured_processing_seconds':sum(item['duration_seconds'] or 0 for item in items),
                'financial_totals':[{'currency':key[0],'category':key[1],'amount':str(value)} for key,value in totals.items()]}

    @staticmethod
    def csv(rows):
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output,fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({key:spreadsheet_safe(value) for key,value in row.items()} for row in rows)
        return output.getvalue()

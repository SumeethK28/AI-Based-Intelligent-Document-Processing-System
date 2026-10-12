"""Atomic additive human-review migration, with a consistent pre-migration backup."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def migrate_review(repository):
    with repository.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='review_events'").fetchone():
            return
        if db.execute('SELECT count(*) FROM documents').fetchone()[0]:
            backup = Path(str(repository.db_path)+'.before_review_v1.'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')+'.db')
            with closing(sqlite3.connect(backup)) as destination:
                db.backup(destination)
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='review_events'").fetchone():
            return
        schema = '''
        ALTER TABLE documents ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE documents ADD COLUMN processing_version_id INTEGER REFERENCES processing_versions(id);
        CREATE TABLE processing_versions (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
          run_id INTEGER REFERENCES processing_runs(id), origin TEXT NOT NULL,
          captured_at TEXT NOT NULL, original_state TEXT NOT NULL);
        CREATE INDEX versions_document ON processing_versions(document_id,id);
        CREATE TABLE review_cases (
          document_id INTEGER PRIMARY KEY REFERENCES documents(id),
          team TEXT NOT NULL, assignee TEXT, case_status TEXT NOT NULL DEFAULT 'open',
          priority TEXT NOT NULL DEFAULT 'normal', updated_at TEXT NOT NULL);
        CREATE INDEX cases_queue ON review_cases(team,case_status,priority,document_id);
        CREATE INDEX document_matched_po ON documents(json_extract(full_result,'$.matched_document_id'));
        CREATE TABLE review_events (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
          processing_version_id INTEGER REFERENCES processing_versions(id), event_type TEXT NOT NULL,
          previous_values TEXT NOT NULL, new_values TEXT NOT NULL, actor TEXT NOT NULL, actor_kind TEXT NOT NULL,
          created_at TEXT NOT NULL, decision TEXT, reason TEXT NOT NULL, notes TEXT NOT NULL,
          validation_results TEXT NOT NULL, rule_versions TEXT,
          previous_revision INTEGER NOT NULL, new_revision INTEGER NOT NULL);
        CREATE INDEX events_document ON review_events(document_id,id);
        '''
        for statement in schema.split(';'):
            if statement.strip():
                db.execute(statement)
        # Snapshot actual available data only. No fabricated historical decisions/events.
        for row in db.execute('SELECT id,full_result,assigned_department,document_type,review_decision FROM documents').fetchall():
            run = db.execute('SELECT id FROM processing_runs WHERE document_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
            version = db.execute('INSERT INTO processing_versions(document_id,run_id,origin,captured_at,original_state) VALUES(?,?,?,?,?)',
                (row['id'],run['id'] if run else None,'legacy_current_snapshot',repository.timestamp(),row['full_result'])).lastrowid
            db.execute('UPDATE documents SET processing_version_id=? WHERE id=?',(version,row['id']))
            team = {'invoice':'Finance','purchase_order':'Procurement','receipt':'Expense Processing','contract':'Legal'}.get(row['document_type'],row['assigned_department'])
            status={'approved':'approved','rejected':'rejected','needs_correction':'awaiting_correction','escalated':'escalated'}.get(row['review_decision'],'open')
            db.execute('INSERT INTO review_cases(document_id,team,case_status,updated_at) VALUES(?,?,?,?)',(row['id'],team,status,repository.timestamp()))
        for table in ('review_events','processing_versions'):
            for action in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Append-only history cannot be modified'); END")
        db.execute('''CREATE TRIGGER document_revision AFTER UPDATE OF full_result,extracted_data,
            review_decision,review_notes,assigned_department,processing_version_id ON documents
            BEGIN UPDATE documents SET revision=old.revision+1 WHERE id=new.id; END''')


def capture_version(repository, db, document_id, run_id, state, origin):
    """Called inside the same transaction as a successful new/reprocessed run."""
    now = repository.timestamp()
    version = db.execute('INSERT INTO processing_versions(document_id,run_id,origin,captured_at,original_state) VALUES(?,?,?,?,?)',
        (document_id,run_id,origin,now,json.dumps(state,ensure_ascii=False))).lastrowid
    db.execute('UPDATE documents SET processing_version_id=? WHERE id=?',(version,document_id))
    db.execute('''INSERT INTO review_cases(document_id,team,updated_at) VALUES(?,?,?)
        ON CONFLICT(document_id) DO UPDATE SET team=excluded.team,assignee=NULL,case_status='open',updated_at=excluded.updated_at''',
        (document_id,{'invoice':'Finance','purchase_order':'Procurement','receipt':'Expense Processing','contract':'Legal'}.get(state.get('document_type'),state.get('assigned_department','Document Review')),now))
    return version

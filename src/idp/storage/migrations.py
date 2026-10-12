"""Additive, backed-up prototype migration. Never rewrite legacy rows."""
from pathlib import Path
import sqlite3
from contextlib import closing
from datetime import datetime, timezone


def migrate(repository):
    with repository.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='batch_jobs'").fetchone():
            return
        if db.execute('SELECT count(*) FROM documents').fetchone()[0]:
            destination = Path(str(repository.db_path) + '.before_batch_v1.' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f') + '.db')
            with closing(sqlite3.connect(destination)) as backup:
                db.backup(backup)
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='batch_jobs'").fetchone():
            return
        schema = '''
        CREATE TABLE batch_jobs (
          id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
          description TEXT NOT NULL, created_at TEXT NOT NULL, reconciled_at TEXT);
        CREATE TABLE batch_items (
          id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batch_jobs(id),
          filename TEXT NOT NULL, file_hash TEXT NOT NULL, source_path TEXT NOT NULL,
          size_bytes INTEGER NOT NULL, pages INTEGER NOT NULL, force_reprocess INTEGER NOT NULL DEFAULT 0,
          state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','processing','completed','duplicate','failed','review_required')),
          attempts INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 0,
          started_at TEXT, completed_at TEXT, document_id INTEGER REFERENCES documents(id),
          run_id INTEGER REFERENCES processing_runs(id), error_category TEXT, safe_error TEXT,
          duration_seconds REAL, result_snapshot TEXT, retain_until TEXT NOT NULL);
        CREATE INDEX batch_items_job ON batch_items(batch_id,state,id);
        CREATE INDEX batch_items_document ON batch_items(document_id,batch_id);
        CREATE TABLE batch_attempts (
          id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES batch_items(id),
          attempt INTEGER NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
          state TEXT NOT NULL, error_category TEXT, safe_error TEXT, duration_seconds REAL);
        ALTER TABLE processing_runs ADD COLUMN operation_key TEXT;
        ALTER TABLE processing_runs ADD COLUMN result_snapshot TEXT;
        CREATE UNIQUE INDEX processing_operation ON processing_runs(operation_key) WHERE operation_key IS NOT NULL;
        CREATE INDEX documents_filters ON documents(document_type,assigned_department,workflow_status,review_decision,id);
        CREATE INDEX documents_received ON documents(created_at,id);
        CREATE TABLE document_search (
          document_id INTEGER PRIMARY KEY REFERENCES documents(id), search_text TEXT NOT NULL,
          po_number TEXT, currency TEXT, amount REAL);
        CREATE INDEX search_po ON document_search(po_number,document_id);
        CREATE INDEX search_money ON document_search(currency,amount,document_id);
        CREATE VIRTUAL TABLE document_fts USING fts5(search_text,tokenize='trigram');
        '''
        for statement in schema.split(';'):
            if statement.strip():
                db.execute(statement)
        expression = "lower(new.filename || ' ' || " + " || ' ' || ".join(
            f"coalesce(json_extract(new.extracted_data,'$.{key}'),'')" for key in
            ('invoice_number','po_number','receipt_number','contract_number','seller','client','vendor','buyer','party_a','party_b')) + ')'
        for event in ('INSERT', 'UPDATE OF filename,extracted_data'):
            trigger = 'insert' if event == 'INSERT' else 'update'
            db.execute(f'''CREATE TRIGGER documents_search_{trigger} AFTER {event} ON documents BEGIN
              INSERT OR REPLACE INTO document_search VALUES(new.id,{expression},
              upper(replace(replace(replace(replace(coalesce(json_extract(new.extracted_data,'$.po_number'),''),' ',''),char(9),''),char(10),''),char(13),'')),
              idp_currency(new.extracted_data),idp_amount(new.extracted_data));
              DELETE FROM document_fts WHERE rowid=new.id;
              INSERT INTO document_fts(rowid,search_text) SELECT document_id,search_text FROM document_search WHERE document_id=new.id;
              END''')
        # Fire the derived-data trigger without modifying original document content.
        db.execute('UPDATE documents SET extracted_data=extracted_data')

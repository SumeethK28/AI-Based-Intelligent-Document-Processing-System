"""Backed-up additive security tables; never invent authenticated legacy actors."""
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone


def migrate_security(repository):
    with repository._connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone():
            return
        if db.execute('SELECT count(*) FROM documents').fetchone()[0]:
            path=Path(str(repository.db_path)+'.before_security_v1.'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')+'.db')
            with closing(sqlite3.connect(path)) as destination: db.backup(destination)
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone(): return
        schema='''
        CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE COLLATE NOCASE,
          password_hash TEXT NOT NULL,role TEXT NOT NULL,departments TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE auth_sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
          created_at REAL NOT NULL,expires_at REAL NOT NULL,last_seen REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX sessions_user ON auth_sessions(user_id,revoked);
        CREATE TABLE login_limits(identifier_hash TEXT PRIMARY KEY,failures INTEGER NOT NULL,window_start REAL NOT NULL,locked_until REAL NOT NULL);
        CREATE TABLE security_events(id INTEGER PRIMARY KEY,event_type TEXT NOT NULL,user_id INTEGER REFERENCES users(id),
          outcome TEXT NOT NULL,resource TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE event_identities(event_table TEXT NOT NULL,event_id INTEGER NOT NULL,user_id INTEGER NOT NULL REFERENCES users(id),
          PRIMARY KEY(event_table,event_id));
        CREATE TABLE download_grants(grant_hash TEXT PRIMARY KEY,session_hash TEXT NOT NULL REFERENCES auth_sessions(token_hash),
          kind TEXT NOT NULL,resource TEXT NOT NULL,expires_at REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX grants_expiry ON download_grants(expires_at);
        '''
        for statement in schema.split(';'):
            if statement.strip(): db.execute(statement)
        for table in ('security_events','event_identities'):
            for action in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Append-only security history'); END")


def migrate_collaboration(repository):
    """Nullable provenance only; existing identities and records remain unchanged."""
    with repository._connect() as db:
        if 'submitted_by' in {row[1] for row in db.execute('PRAGMA table_info(batch_jobs)')}:
            return
        if db.execute('SELECT count(*) FROM documents').fetchone()[0]:
            path=Path(str(repository.db_path)+'.before_collaboration_v1.'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')+'.db')
            with closing(sqlite3.connect(path)) as destination: db.backup(destination)
        db.execute('BEGIN IMMEDIATE')
        if 'submitted_by' in {row[1] for row in db.execute('PRAGMA table_info(batch_jobs)')}:
            return
        db.execute('ALTER TABLE batch_jobs ADD COLUMN submitted_by INTEGER REFERENCES users(id)')
        db.execute('ALTER TABLE batch_jobs ADD COLUMN actor_context TEXT')
        db.execute('ALTER TABLE processing_runs ADD COLUMN actor_context TEXT')
        db.execute('CREATE INDEX batch_submitter ON batch_jobs(submitted_by,created_at)')
        db.execute('CREATE INDEX cases_assignee ON review_cases(assignee,case_status,document_id)')


def migrate_onboarding(repository):
    """Add pending requests and local setup authorization; no existing user changes."""
    with repository._connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='registration_requests'").fetchone(): return
        if any(db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('documents','users','batch_jobs')):
            backup=Path(str(repository.db_path)+'.before_onboarding_v1.'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')+'.db')
            with closing(sqlite3.connect(backup)) as destination: db.backup(destination)
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='registration_requests'").fetchone(): return
        db.execute('CREATE TABLE setup_authorizations(id INTEGER PRIMARY KEY CHECK(id=1),token_hash TEXT,expires_at REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0)')
        db.execute("CREATE TABLE registration_requests(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE COLLATE NOCASE,password_hash TEXT,status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved')),created_at TEXT NOT NULL,approved_at TEXT,approved_by INTEGER REFERENCES users(id),revision INTEGER NOT NULL DEFAULT 0)")
        db.execute('CREATE INDEX registrations_pending ON registration_requests(status,created_at,id)')


def migrate_department_requests(repository):
    """Add untrusted preferences and decline metadata without rebuilding old rows."""
    with repository._connect() as db:
        if 'requested_department' in {row[1] for row in db.execute('PRAGMA table_info(registration_requests)')}: return
        if any(db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('users','registration_requests','documents')):
            backup=Path(str(repository.db_path)+'.before_department_requests_v1.'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')+'.db')
            with closing(sqlite3.connect(backup)) as destination: db.backup(destination)
        db.execute('BEGIN IMMEDIATE')
        if 'requested_department' in {row[1] for row in db.execute('PRAGMA table_info(registration_requests)')}: return
        db.execute('ALTER TABLE registration_requests ADD COLUMN requested_department TEXT')
        db.execute('ALTER TABLE registration_requests ADD COLUMN rejected_by INTEGER REFERENCES users(id)')
        db.execute('ALTER TABLE registration_requests ADD COLUMN rejected_at TEXT')

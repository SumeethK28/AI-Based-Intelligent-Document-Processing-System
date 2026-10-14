"""Add policy tables only; existing documents and append-only histories remain intact."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone


def migrate_policy(repository):
    from idp.policy.schema import DEFAULT
    with repository._connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='policy_versions'").fetchone():
            return
        if db.execute('SELECT count(*) FROM documents').fetchone()[0]:
            backup=Path(str(repository.db_path)+'.before_policy_v1.'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')+'.db')
            with closing(sqlite3.connect(backup)) as destination:
                db.backup(destination)
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='policy_versions'").fetchone():
            return
        schema='''
        CREATE TABLE policy_versions(id INTEGER PRIMARY KEY,config TEXT NOT NULL,actor TEXT NOT NULL,
          reason TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE policy_active(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          version_id INTEGER NOT NULL REFERENCES policy_versions(id),generation INTEGER NOT NULL);
        CREATE TABLE policy_previews(id INTEGER PRIMARY KEY,version_id INTEGER NOT NULL REFERENCES policy_versions(id),
          generation INTEGER NOT NULL,fingerprint TEXT NOT NULL,results TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE policy_activations(id INTEGER PRIMARY KEY,version_id INTEGER NOT NULL REFERENCES policy_versions(id),
          previous_version_id INTEGER REFERENCES policy_versions(id),preview_id INTEGER REFERENCES policy_previews(id),
          actor TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL,generation INTEGER NOT NULL);
        CREATE INDEX policy_history_version ON policy_activations(version_id,id);
        '''
        for statement in schema.split(';'):
            if statement.strip():
                db.execute(statement)
        version=db.execute('INSERT INTO policy_versions(config,actor,reason,created_at) VALUES(?,?,?,?)',
            (json.dumps(DEFAULT,sort_keys=True),'system:policy-migration','Protected baseline defaults; legacy results are not retroactively versioned.',repository.timestamp())).lastrowid
        db.execute('INSERT INTO policy_active VALUES(1,?,0)',(version,))
        db.execute('INSERT INTO policy_activations(version_id,actor,reason,created_at,generation) VALUES(?,?,?,?,0)',
            (version,'system:policy-migration','Initial defaults for new processing only.',repository.timestamp()))
        for table in ('policy_versions','policy_activations','policy_previews'):
            for action in ('UPDATE','DELETE'):
                db.execute(f"CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Append-only policy history cannot be modified'); END")

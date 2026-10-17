"""SQLite persistence for processed documents and processing runs."""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DocumentRepository:
    def __init__(self, db_path: str | Path = "data/idp.db", *, session_token=None, _capability=None, _session_hash=None) -> None:
        from idp.security import INTERNAL
        from idp.security.access import AccessControl
        self.internal = _capability is INTERNAL
        self.session_token = session_token
        self.session_hash = _session_hash
        self._connection_depth = 0
        self._security_pending = []
        self.access = AccessControl(self)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize_database()
        from idp.storage.migrations import migrate
        migrate(self)
        from idp.storage.review_migration import migrate_review
        migrate_review(self)
        from idp.storage.policy_migration import migrate_policy
        migrate_policy(self)
        from idp.storage.security_migration import migrate_security
        migrate_security(self)
        from idp.storage.security_migration import migrate_collaboration
        migrate_collaboration(self)
        from idp.storage.security_migration import migrate_onboarding
        migrate_onboarding(self)

    def require(self, permission):
        return self.access.require(permission)

    def connect(self):
        if not self.internal:
            from idp.security.auth import AccessDenied
            raise AccessDenied('Raw database access is reserved for server maintenance.')
        return self._connect()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Commit/rollback and always close the SQLite connection (Windows-safe)."""
        connection = sqlite3.connect(self.db_path, timeout=10)
        from idp.utils.money import parse_money
        def money(data):
            fields = json.loads(data)
            return parse_money(fields.get('total') or fields.get('contract_value'))
        connection.create_function('idp_amount', 1, lambda data: float(value.amount) if (value := money(data)) else None)
        connection.create_function('idp_currency', 1, lambda data: value.currency if (value := money(data)) else None)
        try:
            self._connection_depth += 1
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            self._connection_depth -= 1
            connection.close()
            if self._connection_depth == 0 and self._security_pending:
                pending,self._security_pending=self._security_pending,[]
                with self._connect() as audit:
                    audit.executemany('INSERT INTO security_events(event_type,user_id,outcome,resource,created_at) VALUES(?,?,?,?,?)',pending)

    @staticmethod
    def timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def calculate_hash(file_path: str | Path) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _encode_result(final_state: dict[str, Any]) -> tuple[str, str]:
        return (
            json.dumps(final_state, ensure_ascii=False),
            json.dumps(final_state.get("extracted_fields", {}), ensure_ascii=False),
        )

    def initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_hash TEXT NOT NULL UNIQUE,
                    document_type TEXT NOT NULL,
                    extracted_data TEXT NOT NULL,
                    full_result TEXT NOT NULL,
                    workflow_status TEXT NOT NULL,
                    assigned_department TEXT NOT NULL,
                    review_decision TEXT NOT NULL DEFAULT 'pending',
                    review_notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS processing_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    is_duplicate INTEGER NOT NULL,
                    processed_at TEXT NOT NULL,
                    FOREIGN KEY (document_id) REFERENCES documents(id)
                );

                CREATE INDEX IF NOT EXISTS idx_processing_runs_document
                    ON processing_runs(document_id);
                """
            )

    def find_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        self.access.intake()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE file_hash = ?", (file_hash,)
            ).fetchone()
        if row is not None:
            self.access.intake(document_id=row['id'])
        return dict(row) if row is not None else None

    def check_duplicate(self, file_path: str | Path) -> dict[str, Any] | None:
        return self.find_by_hash(self.calculate_hash(file_path))

    def save_processed_document(
        self,
        file_path: str | Path,
        filename: str,
        final_state: dict[str, Any],
        operation_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a unique document or record an exact duplicate upload."""
        principal=self.access.intake(final_state)
        file_hash = self.calculate_hash(file_path)
        now = self.timestamp()
        result_json, extracted_json = self._encode_result(final_state)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            principal=self.access.intake(final_state)
            if operation_key:
                prior = connection.execute('SELECT id,document_id,is_duplicate FROM processing_runs WHERE operation_key=?', (operation_key,)).fetchone()
                if prior:
                    return {'document_id':prior['document_id'], 'run_id':prior['id'], 'file_hash':file_hash, 'is_duplicate':bool(prior['is_duplicate'])}
            existing = connection.execute(
                "SELECT id FROM documents WHERE file_hash = ?", (file_hash,)
            ).fetchone()
            if existing is not None:
                document_id = existing["id"]
                self.access.intake(document_id=document_id)
                is_duplicate = True
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO documents (
                        filename, file_hash, document_type, extracted_data,
                        full_result, workflow_status, assigned_department,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        filename,
                        file_hash,
                        final_state.get("document_type", "unknown"),
                        extracted_json,
                        result_json,
                        final_state.get("workflow_status", "manual_review"),
                        final_state.get("assigned_department", "Document Review"),
                        now,
                        now,
                    ),
                )
                document_id = cursor.lastrowid
                is_duplicate = False

            run_cursor = connection.execute(
                """
                INSERT INTO processing_runs
                    (document_id, filename, is_duplicate, processed_at)
                VALUES (?, ?, ?, ?)
                """,
                (document_id, filename, int(is_duplicate), now),
            )
            run_id = run_cursor.lastrowid
            context=None if self.internal else json.dumps({key:principal[key] for key in ('id','username','role','departments')})
            connection.execute('UPDATE processing_runs SET actor_context=? WHERE id=?',(context,run_id))
            connection.execute('UPDATE processing_runs SET operation_key=?,result_snapshot=? WHERE id=?', (operation_key, result_json, run_id))
            if not is_duplicate:
                from idp.storage.review_migration import capture_version
                capture_version(self,connection,document_id,run_id,final_state,'model_result')

        return {
            "document_id": document_id,
            "run_id": run_id,
            "file_hash": file_hash,
            "is_duplicate": is_duplicate,
        }

    def save_reprocessed_document(
        self,
        file_path: str | Path,
        filename: str,
        final_state: dict[str, Any],
        operation_key: str | None = None,
    ) -> dict[str, Any]:
        """Replace the latest result of an existing document and record a new run.

        Reprocessing resets the review decision. This schema keeps only the
        latest full result, not a snapshot per processing run.
        """
        principal=self.access.intake(final_state,force=True)
        file_hash = self.calculate_hash(file_path)
        now = self.timestamp()
        result_json, extracted_json = self._encode_result(final_state)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            principal=self.access.intake(final_state,force=True)
            if operation_key:
                prior = connection.execute('SELECT id,document_id FROM processing_runs WHERE operation_key=?', (operation_key,)).fetchone()
                if prior:
                    return {'document_id':prior['document_id'], 'run_id':prior['id'], 'file_hash':file_hash, 'is_duplicate':False, 'reprocessed':True}
            existing = connection.execute(
                "SELECT * FROM documents WHERE file_hash = ?", (file_hash,)
            ).fetchone()
            if existing is None:
                raise ValueError("Cannot reprocess: document not found in SQLite.")

            document_id = existing["id"]
            connection.execute(
                """
                UPDATE documents SET
                    filename = ?, document_type = ?, extracted_data = ?,
                    full_result = ?, workflow_status = ?,
                    assigned_department = ?, review_decision = 'pending',
                    review_notes = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    filename,
                    final_state.get("document_type", "unknown"),
                    extracted_json,
                    result_json,
                    final_state.get("workflow_status", "manual_review"),
                    final_state.get("assigned_department", "Document Review"),
                    now,
                    document_id,
                ),
            )
            run_cursor = connection.execute(
                """
                INSERT INTO processing_runs
                    (document_id, filename, is_duplicate, processed_at)
                VALUES (?, ?, 0, ?)
                """,
                (document_id, filename, now),
            )
            run_id = run_cursor.lastrowid
            context=None if self.internal else json.dumps({key:principal[key] for key in ('id','username','role','departments')})
            connection.execute('UPDATE processing_runs SET actor_context=? WHERE id=?',(context,run_id))
            connection.execute('UPDATE processing_runs SET operation_key=?,result_snapshot=? WHERE id=?', (operation_key, result_json, run_id))
            from idp.storage.review_migration import capture_version
            from idp.review.service import ReviewService
            version = capture_version(self,connection,document_id,run_id,final_state,'reprocessed_model_result')
            before = dict(existing)
            before['processing_version_id']=version
            ReviewService(self).event(connection,before,'reprocessed',
                {'decision':existing['review_decision'],'processing_version_id':existing['processing_version_id']},
                {'decision':'pending','processing_version_id':version},'system:processing',
                'Explicit forced reprocessing replaced the current result and reopened review.',state=final_state)
            if final_state.get('document_type')=='purchase_order':
                ReviewService(self).invalidate_dependents(connection,document_id,'Referenced PO was reprocessed; fresh invoice review is required.')

        return {
            "document_id": document_id,
            "run_id": run_id,
            "file_hash": file_hash,
            "is_duplicate": False,
            "reprocessed": True,
        }

    def list_documents(self, limit: int = 100) -> list[dict[str, Any]]:
        self.require('documents')
        scope,args=self.access.scope()
        with self._connect() as db:
            return [dict(row) for row in db.execute('SELECT d.id,d.filename,d.document_type,d.workflow_status,d.assigned_department,d.review_decision,d.created_at FROM documents d WHERE '+scope+' ORDER BY d.id DESC LIMIT ?',[*args,max(1,min(limit,1000))])]

    def list_processing_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        self.require('documents')
        scope,args=self.access.scope()
        with self._connect() as db:
            return [dict(row) for row in db.execute('SELECT r.* FROM processing_runs r JOIN documents d ON d.id=r.document_id WHERE '+scope+' ORDER BY r.id DESC LIMIT ?',[*args,max(1,min(limit,1000))])]

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        if not self.internal:
            self.access.document(document_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        if row is None:
            return None
        document = dict(row)
        document["extracted_data"] = json.loads(document["extracted_data"])
        document["full_result"] = json.loads(document["full_result"])
        return document

    def update_review(
        self, document_id: int, decision: str, notes: str = "", *, expected_revision: int | None = None
    ) -> bool:
        if decision not in {"approved", "rejected", "needs_correction"}:
            raise ValueError("Invalid review decision.")
        if self.get_document(document_id) is None:
            return False
        from idp.review.service import ReviewService
        ReviewService(self).decide(document_id,expected_revision,decision,actor='prototype:compatibility-api',reason=notes,notes=notes)
        return True

    def find_purchase_orders(self, po_number: str) -> list[dict[str, Any]]:
        self.require('documents')
        """Return all stored POs with the same normalized PO identifier."""
        def normalize(value: str) -> str:
            return "".join(str(value).upper().split())

        target = normalize(po_number)
        if not target:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, filename, extracted_data
                FROM documents WHERE document_type = ? AND id IN (SELECT document_id FROM document_search WHERE po_number=?)
                """,
                ("purchase_order", target),
            ).fetchall()
        if not self.internal:
            scope,args=self.access.scope()
            with self._connect() as db:
                allowed={row[0] for row in db.execute('SELECT d.id FROM documents d WHERE '+scope,args)}
            rows=[row for row in rows if row['id'] in allowed]

        matches = []
        for row in rows:
            extracted = json.loads(row["extracted_data"])
            stored_number = extracted.get("po_number")
            if stored_number and normalize(stored_number) == target:
                matches.append({
                    "document_id": row["id"],
                    "filename": row["filename"],
                    "extracted_fields": extracted,
                })
        return matches

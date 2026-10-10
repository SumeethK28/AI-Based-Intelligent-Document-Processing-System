
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contextlib import contextmanager
from collections.abc import Iterator

class DocumentRepository:

    def __init__(
        self,
        db_path: str | Path = "data/idp.db"
    ):
        self.db_path = Path(db_path)

        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.initialize_database()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:

        connection = sqlite3.connect(
            self.db_path,
            timeout=10,
        )

        try:
            connection.row_factory = sqlite3.Row

            connection.execute(
                "PRAGMA foreign_keys = ON"
            )

            with connection:
                yield connection

        finally:
            connection.close()

    @staticmethod
    def timestamp() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def calculate_hash(
        file_path: str | Path
    ) -> str:

        digest = hashlib.sha256()

        with open(file_path, "rb") as file:

            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    # ==================================================
    # DATABASE SCHEMA
    # ==================================================

    def initialize_database(self) -> None:

        with self.connect() as connection:

            connection.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    filename TEXT NOT NULL,

                    file_hash TEXT NOT NULL UNIQUE,

                    document_type TEXT NOT NULL,

                    extracted_data TEXT NOT NULL,

                    full_result TEXT NOT NULL,

                    workflow_status TEXT NOT NULL,

                    assigned_department TEXT NOT NULL,

                    review_decision TEXT NOT NULL
                        DEFAULT 'pending',

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

                    FOREIGN KEY(document_id)
                        REFERENCES documents(id)
                );

                CREATE INDEX IF NOT EXISTS
                    idx_processing_runs_document
                    ON processing_runs(document_id);
            """)

    # ==================================================
    # DUPLICATE LOOKUP
    # ==================================================

    def find_by_hash(
        self,
        file_hash: str
    ) -> dict[str, Any] | None:

        with self.connect() as connection:

            row = connection.execute(
                """
                SELECT *
                FROM documents
                WHERE file_hash = ?
                """,
                (file_hash,),
            ).fetchone()

        return dict(row) if row else None

    def check_duplicate(
        self,
        file_path: str | Path
    ) -> dict[str, Any] | None:

        file_hash = self.calculate_hash(
            file_path
        )

        return self.find_by_hash(
            file_hash
        )

    # ==================================================
    # SAVE DOCUMENT
    # ==================================================

    def save_processed_document(
        self,
        file_path: str | Path,
        filename: str,
        final_state: dict[str, Any],
    ) -> dict[str, Any]:

        file_hash = self.calculate_hash(
            file_path
        )

        now = self.timestamp()

        # Serialize the completed agent state.
        # The current agent state uses JSON-compatible
        # primitives such as strings, lists and dicts.
        result_json = json.dumps(
            final_state,
            ensure_ascii=False,
        )

        extracted_json = json.dumps(
            final_state.get("extracted_fields", {}),
            ensure_ascii=False,
        )

        with self.connect() as connection:

            # Transaction is serialized before we check
            # and insert to avoid duplicate race conditions.
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                """
                SELECT id
                FROM documents
                WHERE file_hash = ?
                """,
                (file_hash,),
            ).fetchone()

            if existing is not None:

                document_id = existing["id"]
                is_duplicate = True

            else:

                cursor = connection.execute(
                    """
                    INSERT INTO documents (
                        filename,
                        file_hash,
                        document_type,
                        extracted_data,
                        full_result,
                        workflow_status,
                        assigned_department,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        filename,
                        file_hash,
                        final_state.get(
                            "document_type",
                            "unknown",
                        ),
                        extracted_json,
                        result_json,
                        final_state.get(
                            "workflow_status",
                            "manual_review",
                        ),
                        final_state.get(
                            "assigned_department",
                            "Document Review",
                        ),
                        now,
                        now,
                    ),
                )

                document_id = cursor.lastrowid
                is_duplicate = False

            run_cursor = connection.execute(
                """
                INSERT INTO processing_runs (
                    document_id,
                    filename,
                    is_duplicate,
                    processed_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    document_id,
                    filename,
                    int(is_duplicate),
                    now,
                ),
            )

            run_id = run_cursor.lastrowid

        return {
            "document_id": document_id,
            "run_id": run_id,
            "file_hash": file_hash,
            "is_duplicate": is_duplicate,
        }

    # ==================================================
    # DOCUMENT HISTORY
    # ==================================================

    def list_documents(
        self,
        limit: int = 100
    ) -> list[dict[str, Any]]:

        with self.connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    id,
                    filename,
                    document_type,
                    workflow_status,
                    assigned_department,
                    review_decision,
                    created_at
                FROM documents
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def list_processing_runs(
        self,
        limit: int = 100
    ) -> list[dict[str, Any]]:

        with self.connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    id,
                    document_id,
                    filename,
                    is_duplicate,
                    processed_at
                FROM processing_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def get_document(
        self,
        document_id: int
    ) -> dict[str, Any] | None:

        with self.connect() as connection:

            row = connection.execute(
                """
                SELECT *
                FROM documents
                WHERE id = ?
                """,
                (document_id,),
            ).fetchone()

        if row is None:
            return None

        document = dict(row)

        document["extracted_data"] = json.loads(
            document["extracted_data"]
        )

        document["full_result"] = json.loads(
            document["full_result"]
        )

        return document

    # ==================================================
    # REVIEW ACTIONS
    # ==================================================

    def update_review(
        self,
        document_id: int,
        decision: str,
        notes: str = "",
    ) -> bool:

        if decision not in {
            "approved",
            "rejected",
            "needs_correction",
        }:
            raise ValueError(
                "Invalid review decision."
            )

        with self.connect() as connection:

            cursor = connection.execute(
                """
                UPDATE documents
                SET
                    review_decision = ?,
                    review_notes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    decision,
                    notes,
                    self.timestamp(),
                    document_id,
                ),
            )

            return cursor.rowcount > 0

    def find_purchase_orders(
        self,
        po_number: str,
    ) -> list[dict]:

        def normalize(value: str) -> str:
            return "".join(
                str(value).upper().split()
            )

        target = normalize(po_number)

        if not target:
            return []

        matches = []

        with self.connect() as connection:

            rows = connection.execute(
                """
                SELECT id, filename, extracted_data
                FROM documents
                WHERE document_type = ?
                """,
                ("purchase_order",),
            ).fetchall()

        for row in rows:

            extracted = json.loads(
                row["extracted_data"]
            )

            stored_number = extracted.get(
                "po_number"
            )

            if (
                stored_number
                and normalize(stored_number) == target
            ):
                matches.append({
                    "document_id": row["id"],
                    "filename": row["filename"],
                    "extracted_fields": extracted,
                })

        return matches

"""Read-only operations queries; unique documents and submissions stay distinct."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from idp.storage.repository import DocumentRepository
from idp.utils.money import parse_money


@dataclass(frozen=True)
class DocumentFilters:
    document_type: str = ""
    department: str = ""
    status: str = ""
    review_decision: str = ""
    start_date: date | None = None
    end_date: date | None = None
    search: str = ""
    currency: str = ""
    min_amount: float | None = None
    max_amount: float | None = None
    batch_id: str = ""


class OperationsQueries:
    def __init__(self, repository: DocumentRepository):
        self.repository = repository

    @staticmethod
    def _where(filters: DocumentFilters) -> tuple[str, list[Any]]:
        clauses, parameters = [], []
        for column, value in (("document_type", filters.document_type), ("assigned_department", filters.department),
                              ("workflow_status", filters.status), ("review_decision", filters.review_decision)):
            if value:
                clauses.append(f"d.{column} = ?")
                parameters.append(value)
        if filters.start_date:
            clauses.append("d.created_at >= ?")
            parameters.append(filters.start_date.isoformat())
        if filters.end_date:
            clauses.append("d.created_at < ?")
            parameters.append((filters.end_date+timedelta(days=1)).isoformat())
        if filters.search.strip():
            query = filters.search.strip().lower()
            if len(query) >= 3:
                clauses.append('d.id IN (SELECT rowid FROM document_fts WHERE document_fts MATCH ?)')
                parameters.append('"' + query.replace('"','""') + '"')
            else:
                clauses.append('d.id IN (SELECT document_id FROM document_search WHERE instr(search_text,?)>0)')
                parameters.append(query)
        money_clauses, money_parameters = [], []
        for column, operator, value in (('currency','=',filters.currency),('amount','>=',filters.min_amount),('amount','<=',filters.max_amount)):
            if value is not None and value != '':
                money_clauses.append(f'{column}{operator}?')
                money_parameters.append(value)
        if money_clauses:
            clauses.append('d.id IN (SELECT document_id FROM document_search WHERE '+ ' AND '.join(money_clauses)+')')
            parameters.extend(money_parameters)
        if filters.batch_id:
            clauses.append('d.id IN (SELECT document_id FROM batch_items WHERE batch_id=?)')
            parameters.append(filters.batch_id)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters

    def options(self) -> dict[str, list[str]]:
        with self.repository.connect() as connection:
            return {key: [row[0] for row in connection.execute(f"SELECT DISTINCT {column} FROM documents ORDER BY {column}")]
                    for key, column in (("department", "assigned_department"), ("document_type", "document_type"),
                                        ("status", "workflow_status"), ("review_decision", "review_decision"))}

    def overview(self, filters: DocumentFilters = DocumentFilters()) -> dict[str, Any]:
        where, parameters = self._where(filters)
        with self.repository.connect() as connection:
            counts = dict(connection.execute("""
                SELECT COUNT(*) AS unique_documents,
                  coalesce(sum(json_extract(d.full_result, '$.validation_passed') = 1), 0) AS validated,
                  coalesce(sum(json_extract(d.full_result, '$.validation_passed') = 0), 0) AS validation_failed,
                  coalesce(sum(d.review_decision = 'pending'), 0) AS pending_decisions,
                  coalesce(sum(d.review_decision = 'pending' AND d.workflow_status IN
                    ('manual_review', 'anomaly_review', 'unclassified_review')), 0) AS review_exceptions,
                  coalesce(sum(json_extract(d.full_result, '$.cross_document_status') = 'mismatch'), 0) AS po_mismatches,
                  coalesce(sum(d.review_decision = 'pending' AND d.workflow_status = 'pending_department_review'), 0) AS department_pending
                FROM documents d
                """ + where, parameters).fetchone())
            counts.update(dict(connection.execute("""
                SELECT COUNT(*) AS submissions, coalesce(sum(r.is_duplicate), 0) AS duplicate_submissions
                FROM processing_runs r JOIN documents d ON d.id = r.document_id
                """ + where, parameters).fetchone()))
            distributions = {}
            for label, column in (("types", "document_type"), ("statuses", "workflow_status"), ("decisions", "review_decision")):
                distributions[label] = [dict(row) for row in connection.execute(
                    f"SELECT d.{column} AS category, COUNT(*) AS documents FROM documents d" + where + f" GROUP BY d.{column} ORDER BY documents DESC", parameters)]
            departments = [dict(row) for row in connection.execute("""
                SELECT d.assigned_department AS department, COUNT(*) AS documents,
                sum(d.review_decision = 'pending') AS awaiting_decision FROM documents d
                """ + where + " GROUP BY d.assigned_department ORDER BY awaiting_decision DESC", parameters)]
            activity = [dict(row) for row in connection.execute("""
                SELECT r.id AS run_id, r.document_id, r.filename, r.is_duplicate, r.processed_at
                FROM processing_runs r JOIN documents d ON d.id = r.document_id
                """ + where + " ORDER BY r.id DESC LIMIT 10", parameters)]
            daily = [dict(row) for row in connection.execute("""
                SELECT substr(r.processed_at, 1, 10) AS day, COUNT(*) AS submissions,
                sum(r.is_duplicate) AS duplicates FROM processing_runs r JOIN documents d ON d.id = r.document_id
                """ + where + " GROUP BY substr(r.processed_at, 1, 10) ORDER BY day", parameters)]
        return {**counts, **distributions, "departments": departments, "activity": activity, "daily": daily,
                "invoice_values": self.invoice_values(filters)}

    def page(self, filters: DocumentFilters = DocumentFilters(), *, page: int = 1, page_size: int = 20,
             sort: str = "Newest first") -> tuple[list[dict[str, Any]], int]:
        where, parameters = self._where(filters)
        page_size = max(1, min(page_size, 100))
        ordering = {"Newest first": "d.id DESC", "Oldest first": "d.id ASC", "Filename": "d.filename COLLATE NOCASE ASC, d.id ASC"}.get(sort, "d.id DESC")
        with self.repository.connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM documents d" + where, parameters).fetchone()[0]
            rows = connection.execute("""
                SELECT d.id, d.filename, d.document_type, d.workflow_status, d.assigned_department,
                d.review_decision, d.created_at, json_extract(d.full_result, '$.validation_passed') AS validation_passed,
                json_extract(d.full_result, '$.cross_document_status') AS cross_document_status
                FROM documents d
                """ + where + f" ORDER BY {ordering} LIMIT ? OFFSET ?",
                [*parameters, page_size, (max(1, page) - 1) * page_size]).fetchall()
        return [dict(row) for row in rows], total

    def document_runs(self, document_id: int) -> list[dict[str, Any]]:
        with self.repository.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id, filename, is_duplicate, processed_at, result_snapshot IS NOT NULL AS snapshot_available FROM processing_runs WHERE document_id = ? ORDER BY id DESC", (document_id,))]

    def export(self, filters=DocumentFilters(), limit=5000):
        where, parameters = self._where(filters)
        with self.repository.connect() as db:
            total = db.execute('SELECT count(*) FROM documents d'+where,parameters).fetchone()[0]
            if total > limit:
                raise ValueError('Export is limited to 5,000 records. Narrow your filters.')
            rows = db.execute('SELECT d.id,d.filename,d.document_type,d.workflow_status,d.assigned_department,d.review_decision,d.extracted_data FROM documents d'+where+' ORDER BY d.id',parameters).fetchall()
        import json
        return [{**dict(row),'extracted_data':json.loads(row['extracted_data'])} for row in rows]

    def exceptions(self, filters: DocumentFilters) -> list[dict[str, Any]]:
        where, parameters = self._where(filters)
        where += " AND " if where else " WHERE "
        where += "d.review_decision = 'pending' AND d.workflow_status IN ('manual_review', 'anomaly_review', 'unclassified_review')"
        with self.repository.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT d.id, d.filename, d.document_type, d.assigned_department, d.workflow_status FROM documents d" + where + " ORDER BY d.created_at ASC, d.id ASC LIMIT 10", parameters)]

    def invoice_values(self, filters: DocumentFilters) -> list[dict[str, Any]]:
        import json
        where, parameters = self._where(filters)
        where += " AND d.document_type = 'invoice'" if where else " WHERE d.document_type = 'invoice'"
        totals: dict[tuple[str, str], tuple[Decimal, int]] = {}
        with self.repository.connect() as connection:
            # Stream only monetary data and decision flags, not entire OCR/agent states.
            for row in connection.execute("""
                SELECT d.extracted_data, d.review_decision, d.workflow_status,
                json_extract(d.full_result, '$.validation_passed') AS valid,
                json_extract(d.full_result, '$.requires_review') AS needs_review
                FROM documents d
                """ + where, parameters):
                amount = parse_money(json.loads(row["extracted_data"]).get("total"))
                if amount is None:
                    continue
                category = ("Rejected" if row["review_decision"] == "rejected" else
                            "Flagged / correction required" if not row["valid"] or row["needs_review"] or row["workflow_status"] != "pending_department_review" or row["review_decision"] == "needs_correction" else
                            "Review approved" if row["review_decision"] == "approved" else "Pending decision")
                key = (amount.currency or "Unspecified currency", category)
                previous, count = totals.get(key, (Decimal("0"), 0))
                totals[key] = (previous + amount.amount, count + 1)
        return [{"currency": currency, "category": category, "invoice_count": count, "extracted_value": format(value, ".2f")}
                for (currency, category), (value, count) in sorted(totals.items())]

"""Real SQLite query tests; sample processing uses the simulated test provider."""
import json
from datetime import date

from _test_support import PipelineFixture
from idp.storage.operations import DocumentFilters, OperationsQueries


class OperationsTests(PipelineFixture):
    def test_spreadsheet_formula_text_is_escaped_without_changing_original(self):
        from idp.utils.exports import spreadsheet_safe
        original = {"seller": "=WEBSERVICE(\"https://example.invalid\")", "total": "INR 20.00"}
        for value in (original["seller"], " +SUM(1,2)", "@SUM(1,2)", "\t=1+1", "-1+1"):
            self.assertTrue(spreadsheet_safe(value).startswith("'"))
        self.assertEqual(spreadsheet_safe(original["total"]), original["total"])
        self.assertTrue(original["seller"].startswith("="))
        self.assertEqual(spreadsheet_safe(20), 20)

    def invoice(self, name, total="USD 20.00"):
        return self.process(name, "invoice", {"invoice_number": name, "seller": "Supplier", "client": "Client",
                                               "issue_date": "2026-10-01", "total": total})

    def test_duplicate_and_reprocess_do_not_double_count_invoice_values(self):
        result = self.invoice("INV-1")
        self.pipeline.process(self.root / "INV-1")
        self.pipeline.process(self.root / "INV-1", force_reprocess=True)
        data = OperationsQueries(self.pipeline.repository).overview()
        self.assertEqual(data["unique_documents"], 1)
        self.assertEqual(data["submissions"], 3)
        self.assertEqual(data["duplicate_submissions"], 1)
        self.assertEqual(data["invoice_values"], [{"currency": "USD", "category": "Pending decision", "invoice_count": 1, "extracted_value": "20.00"}])

    def test_currency_and_review_categories_stay_separate(self):
        approved = self.invoice("INV-1")
        self.pipeline.repository.update_review(approved["document_id"], "approved",'Verified fixture',expected_revision=self.pipeline.repository.get_document(approved['document_id'])['revision'])
        self.invoice("INV-2", "INR 100.00")
        rejected = self.invoice("INV-3", "EUR 30.00")
        self.pipeline.repository.update_review(rejected["document_id"], "rejected",'Rejected fixture',expected_revision=self.pipeline.repository.get_document(rejected['document_id'])['revision'])
        self.invoice("INV-4", "40.00")
        unsafe = self.process("INV-5", "invoice", {"invoice_number": "INV-5", "issue_date": "2026-10-01", "seller": "Supplier", "client": "Client", "total": "USD 50.00", "po_reference": "PO-missing"})
        # Simulate an existing legacy unsafe approval; the new API must block creating it.
        with self.pipeline.repository.connect() as db:
            db.execute("UPDATE documents SET review_decision='approved' WHERE id=?",(unsafe['document_id'],))
        data = OperationsQueries(self.pipeline.repository).overview()
        groups = {(row["currency"], row["category"]): row["extracted_value"] for row in data["invoice_values"]}
        self.assertEqual(groups[("USD", "Review approved")], "20.00")
        self.assertEqual(groups[("USD", "Flagged / correction required")], "50.00")
        self.assertEqual(groups[("INR", "Pending decision")], "100.00")
        self.assertEqual(groups[("EUR", "Rejected")], "30.00")
        self.assertIn(("Unspecified currency", "Pending decision"), groups)

    def test_literal_search_filters_dates_and_pagination(self):
        first = self.invoice("INV-A")
        second = self.invoice("INV-B", "INR 10.00")
        queries = OperationsQueries(self.pipeline.repository)
        rows, total = queries.page(DocumentFilters(search="INV-A"))
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["id"], first["document_id"])
        self.assertEqual(queries.page(DocumentFilters(search="' OR 1=1 --"))[1], 0)
        self.assertEqual(queries.page(DocumentFilters(search="%"))[1], 0)
        self.assertEqual(queries.page(DocumentFilters(department="Missing"))[1], 0)
        self.assertEqual(queries.page(DocumentFilters(start_date=date(2099, 1, 1)))[1], 0)
        page1, total = queries.page(page=1, page_size=1)
        page2, _ = queries.page(page=2, page_size=1)
        self.assertEqual(total, 2)
        self.assertNotEqual(page1[0]["id"], page2[0]["id"])

    def test_full_cohort_counts_beyond_old_thousand_record_cap(self):
        state = {"document_type": "receipt", "validation_passed": True, "extracted_fields": {}, "cross_document_status": "not_applicable"}
        with self.pipeline.repository.connect() as connection:
            connection.executemany("""
                INSERT INTO documents(filename,file_hash,document_type,extracted_data,full_result,workflow_status,
                assigned_department,created_at,updated_at) VALUES(?,?,'receipt','{}',?,'pending_department_review','Expense Processing',?,?)
                """, [(f"receipt{i}", str(i), json.dumps(state), "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00") for i in range(1005)])
        queries = OperationsQueries(self.pipeline.repository)
        self.assertEqual(queries.overview()["unique_documents"], 1005)
        self.assertEqual(queries.overview()["validated"], 1005)
        rows, total = queries.page(page=51)
        self.assertEqual(total, 1005)
        self.assertEqual(len(rows), 5)

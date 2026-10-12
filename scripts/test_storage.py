"""SQLite component tests use disposable databases only."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from idp.storage.repository import DocumentRepository


class StorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repository = DocumentRepository(self.root / "test.db")
        self.document = self.root / "invoice.txt"
        self.document.write_text("invoice")
        self.state = {"document_type": "invoice", "extracted_fields": {"seller": "Café"}}

    def save(self):
        return self.repository.save_processed_document(self.document, self.document.name, self.state)

    def test_save_reopen_and_duplicate(self):
        saved = self.save()
        reopened = DocumentRepository(self.root / "test.db")
        self.assertEqual(reopened.get_document(saved["document_id"])["full_result"], self.state)
        self.assertEqual(reopened.check_duplicate(self.document)["id"], saved["document_id"])
        duplicate = self.save()
        self.assertTrue(duplicate["is_duplicate"])
        self.assertEqual(len(reopened.list_documents()), 1)
        self.assertEqual(len(reopened.list_processing_runs()), 2)
        self.assertIsNone(reopened.get_document(999))

    def test_reprocessing_resets_review(self):
        saved = self.save()
        self.assertTrue(self.repository.update_review(saved["document_id"], "rejected", "Incomplete source checked",expected_revision=self.repository.get_document(saved['document_id'])['revision']))
        updated = {**self.state, "extracted_fields": {"total": "INR 50.00"}}
        result = self.repository.save_reprocessed_document(self.document, "renamed.txt", updated)
        stored = self.repository.get_document(result["document_id"])
        self.assertEqual(result["document_id"], saved["document_id"])
        self.assertEqual(stored["full_result"], updated)
        self.assertEqual(stored["review_decision"], "pending")
        self.assertIsNone(stored["review_notes"])
        self.assertFalse(self.repository.list_processing_runs()[0]["is_duplicate"])

    def test_reject_invalid_review_and_missing_reprocess(self):
        with self.assertRaises(ValueError):
            self.repository.update_review(1, "invalid")
        with self.assertRaises(ValueError):
            self.repository.save_reprocessed_document(self.document, "x", self.state)
        self.assertFalse(self.repository.update_review(999, "approved"))

    def test_transaction_rollback_and_foreign_keys(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.repository.connect() as connection:
                connection.execute("INSERT INTO processing_runs(document_id, filename, is_duplicate, processed_at) VALUES (999, 'x', 0, 'now')")
        self.assertEqual(self.repository.list_processing_runs(), [])
        with self.repository.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()

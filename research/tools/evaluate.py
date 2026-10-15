"""Measured live evaluation on existing samples; never uses simulated providers."""
from idp.security import INTERNAL
import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from idp.llm.provider import GroqProvider
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
from idp.utils.money import parse_money
from idp.agents.validation_agent import ValidationAgent
from idp.llm.schemas import AIExtractionResult


class RecordingGroqProvider(GroqProvider):
    """Record parsed live extraction before evidence/layout fallbacks."""
    last_extraction = None

    def generate_structured(self, *args, **kwargs):
        result = super().generate_structured(*args, **kwargs)
        if isinstance(result, AIExtractionResult):
            self.last_extraction = result.model_dump()
        return result


GROUND_TRUTH = {
    "purchase_order_1023.pdf": ("purchase_order", {"po_number": "PO-1023", "order_date": "10/10/2026", "vendor": "ABC Technologies", "buyer": "XYZ Company", "total": "INR 42000.00"}, "not_applicable", "pending_department_review", "Procurement"),
    "batch1-0004.jpg": ("invoice", {"invoice_number": "16273983", "issue_date": "04/01/2017", "seller": "Reyes, Holloway and Lee", "client": "Castillo LLC", "tax_id": "909-83-7738", "iban": "GB96VWUL52026848004193", "subtotal": "$744,60", "tax": "$74,46", "total": "$ 819,06"}, "not_checked", "pending_department_review", "Finance"),
    "invoice_matching.pdf": ("invoice", {"invoice_number": "INV-501", "issue_date": "10/10/2026", "seller": "ABC Technologies", "client": "XYZ Company", "total": "INR 42000.00", "po_reference": "PO-1023"}, "matched", "pending_department_review", "Finance"),
    "invoice_mismatch.pdf": ("invoice", {"invoice_number": "INV-502", "issue_date": "10/10/2026", "seller": "ABC Technologies", "client": "XYZ Company", "total": "INR 50000.00", "po_reference": "PO-1023"}, "mismatch", "manual_review", "Document Review"),
    "invoice_unknown_po.pdf": ("invoice", {"invoice_number": "INV-503", "issue_date": "10/10/2026", "seller": "ABC Technologies", "client": "XYZ Company", "total": "INR 42000.00", "po_reference": "PO-9999"}, "unmatched", "manual_review", "Document Review"),
}


def main():
    assert platform.python_version() == "3.14.6"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output = Path("results") / ("evaluation_" + stamp)
    output.mkdir(parents=True)
    provider = RecordingGroqProvider()
    pipeline = AgenticDocumentPipeline(output / "evaluation.db", llm=provider, _capability=INTERNAL)
    report = {"python": platform.python_version(), "model": provider.model, "started_at_utc": stamp,
              "conditions": "Real RapidOCR + Groq, new isolated SQLite DB, PO first, serial processing, no mocks. Timings include OCR/API/retries/SQLite and exclude construction and inter-document pacing.",
              "ground_truth_source": "PDF embedded source text; standard invoice visually transcribed in prior live verification; monetary values compared by amount and currency, other values by normalized whitespace/case.",
              "dataset_size": len(GROUND_TRUTH), "documents": []}
    for index, (name, (kind, expected, cross, routing, department)) in enumerate(GROUND_TRUTH.items()):
        if index:
            time.sleep(15)
        print("LIVE EVALUATION: " + name, flush=True)
        path = Path("data/samples") / (name if name.endswith(".jpg") else "cross_document/" + name)
        started = time.perf_counter()
        entry = {"filename": name, "expected": expected, "expected_classification": kind,
                 "expected_cross_document": cross, "expected_routing": routing, "expected_department": department}
        try:
            result = pipeline.process(path)
            entry["seconds"] = time.perf_counter() - started
            state = result["state"]
            entry["state"] = state
            entry["raw_model_extraction"] = provider.last_extraction
            entry["completed"] = True
            entry["classification_correct"] = state["document_type"] == kind
            entry["cross_document_correct"] = state["cross_document_status"] == cross
            entry["routing_correct"] = state["workflow_status"] == routing and state["assigned_department"] == department
            comparison = {}
            for field, value in expected.items():
                actual = state["extracted_fields"].get(field)
                correct = (parse_money(actual) == parse_money(value)) if field in {"total", "subtotal", "tax"} else " ".join(str(actual or "").casefold().split()) == " ".join(value.casefold().split())
                comparison[field] = {"expected": value, "actual": actual, "correct": correct,
                                     "mandatory": field in ValidationAgent.REQUIRED_FIELDS[kind]}
            entry["field_comparison"] = comparison
            entry["persistence_matches"] = pipeline.repository.get_document(result["document_id"])["full_result"] == state
            print(json.dumps({"seconds": round(entry["seconds"], 3), "classification": state["document_type"], "fields": state["extracted_fields"], "validation": state["validation_passed"], "cross_document": state["cross_document_status"], "routing": state["workflow_status"]}), flush=True)
        except Exception as error:
            entry.update(completed=False, seconds=time.perf_counter() - started, error_type=type(error).__name__, http_status=getattr(error, "status_code", None))
            print("LIVE evaluation failed: " + type(error).__name__, flush=True)
        report["documents"].append(entry)
        (output / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    completed = [entry for entry in report["documents"] if entry["completed"]]
    comparisons = [field for entry in completed for field in entry["field_comparison"].values()]
    report["metrics"] = {"attempted": len(report["documents"]), "completed": len(completed),
                         "classification_correct": sum(entry["classification_correct"] for entry in completed),
                         "cross_document_correct": sum(entry["cross_document_correct"] for entry in completed),
                         "routing_correct": sum(entry["routing_correct"] for entry in completed),
                         "expected_fields_completed": len(comparisons), "fields_correct": sum(field["correct"] for field in comparisons),
                         "mandatory_fields": sum(field["mandatory"] for field in comparisons),
                         "mandatory_fields_correct": sum(field["mandatory"] and field["correct"] for field in comparisons),
                         "mean_seconds_completed": statistics.mean(entry["seconds"] for entry in completed) if completed else None}
    report["limitations"] = "Five existing samples, only invoice/PO types; four related synthetic PDFs and one invoice image. No receipt/contract live evaluation, no concurrency/load testing, small sample does not establish general accuracy. Missing optional source fields count against field recall. No-source optional fields and unsupported extras are not in the recall denominator; full actual fields retained for inspection. Failed calls reported separately; rates must state completed denominator."
    (output / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Evaluation saved: " + str(output), flush=True)


if __name__ == "__main__":
    main()

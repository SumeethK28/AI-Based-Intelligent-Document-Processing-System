"""Generate labeled synthetic samples and evaluate with real RapidOCR/Groq.

Run from the project root. All artifacts and the isolated DB go under results;
the production database and prior evaluations are never modified.
"""
import json
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from idp.agents.validation_agent import ValidationAgent
from idp.llm.provider import GroqProvider
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline
from idp.utils.money import parse_money


RECEIPT = {"receipt_number": "R-1001", "seller": "Northstar Store", "issue_date": "2026-10-10",
           "subtotal": "INR 100.00", "tax": "INR 18.00", "total": "INR 118.00", "payment_method": "Cash"}
CONTRACT = {"contract_title": "Services Agreement", "contract_number": "C-1001", "party_a": "Northstar Services Ltd",
            "party_b": "Orion Retail Ltd", "effective_date": "2026-10-10", "expiration_date": "2027-10-10",
            "contract_value": "INR 50000.00", "governing_law": "India"}
LABELS = {"receipt_number": "Receipt Number", "seller": "Merchant", "issue_date": "Transaction Date",
          "subtotal": "Subtotal", "tax": "Tax", "total": "Total", "payment_method": "Payment Method",
          "contract_number": "Contract Number", "party_a": "Party A", "party_b": "Party B",
          "effective_date": "Effective Date", "expiration_date": "Expiration Date", "contract_value": "Contract Value",
          "governing_law": "Governing Law"}
CASES = [
    ("receipt_valid", "receipt", RECEIPT, True, "Expense Processing", [], ["Cash Tendered: INR 200.00", "Change Returned: INR 82.00", "Payment received in full."]),
    ("receipt_arithmetic_mismatch", "receipt", {**RECEIPT, "receipt_number": "R-1002", "total": "INR 130.00"}, False, "Document Review", ["VALIDATION_FAILURE"], ["Payment received in full."]),
    ("receipt_large_amount", "receipt", {**RECEIPT, "receipt_number": "R-1003", "subtotal": "INR 110000.00", "tax": "INR 19800.00", "total": "INR 129800.00"}, True, "Document Review", ["LARGE_AMOUNT"], ["Payment received in full."]),
    ("contract_valid", "contract", CONTRACT, True, "Legal", [], ["The parties agree to provide and pay for consulting services."]),
    ("contract_missing_date", "contract", {k: v for k, v in {**CONTRACT, "contract_number": "C-1002"}.items() if k != "effective_date"}, False, "Document Review", ["VALIDATION_FAILURE"], ["The parties agree to consulting services. Effective date not specified."]),
    ("contract_three_parties", "contract", {**CONTRACT, "contract_number": "C-1003"}, False, "Document Review", ["VALIDATION_FAILURE"], ["Party C: Vega Holdings Ltd", "All three parties agree to these consulting terms."]),
    ("contract_invalid_dates", "contract", {**CONTRACT, "contract_number": "C-1004", "expiration_date": "2025-10-10"}, False, "Document Review", ["VALIDATION_FAILURE"], ["The parties agree to consulting services."]),
    ("contract_large_value", "contract", {**CONTRACT, "contract_number": "C-1005", "contract_value": "INR 150000.00"}, True, "Document Review", ["LARGE_AMOUNT"], ["The parties agree to consulting services."]),
]


def main():
    assert platform.python_version() == "3.14.6"
    output = Path("results") / ("receipt_contract_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
    samples = output / "samples"
    samples.mkdir(parents=True)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 38)
    manifest = []
    for name, kind, fields, valid, department, anomalies, extra in CASES:
        lines = ["SYNTHETIC TEST SAMPLE - NOT A REAL DOCUMENT", "SALES RECEIPT" if kind == "receipt" else fields["contract_title"]]
        lines += [LABELS.get(key, key) + ": " + value for key, value in fields.items() if key != "contract_title"]
        lines += extra
        image = Image.new("RGB", (1900, 1200), "white")
        draw = ImageDraw.Draw(image)
        for index, line in enumerate(lines):
            draw.text((65, 45 + 70 * index), line, font=font, fill="black")
        image.save(samples / (name + ".png"))
        manifest.append({"name": name, "type": kind, "source_lines": lines, "expected_fields": fields,
                         "expected_validation": valid, "expected_department": department, "expected_anomalies": anomalies})
    (output / "ground_truth.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    provider = GroqProvider()
    pipeline = AgenticDocumentPipeline(output / "evaluation.db", llm=provider)
    report = {"python": platform.python_version(), "model": provider.model, "dataset_size": len(CASES),
              "conditions": "Real RapidOCR and configured Groq; eight generated synthetic PNGs, serial calls, isolated fresh SQLite DB. Timings exclude initialization and 15-second inter-document pacing.",
              "limitations": "Synthetic single-page English documents in one clean layout; no real-world scan variability or broad accuracy claim. Contracts test metadata support, not legal validity. No mocks in this evaluation.", "documents": []}
    for index, expected in enumerate(manifest):
        if index:
            time.sleep(15)
        print("LIVE: " + expected["name"], flush=True)
        entry = {**expected}
        started = time.perf_counter()
        try:
            result = pipeline.process(samples / (expected["name"] + ".png"))
            entry["seconds"] = time.perf_counter() - started
            state = result["state"]
            entry["state"] = state
            entry["completed"] = True
            comparisons = {}
            for field, value in expected["expected_fields"].items():
                actual = state["extracted_fields"].get(field)
                correct = parse_money(actual) == parse_money(value) if field in ValidationAgent.AMOUNT_FIELDS else ValidationAgent.normalize_text(actual or "") == ValidationAgent.normalize_text(value)
                comparisons[field] = {"expected": value, "actual": actual, "correct": correct}
            entry["field_comparison"] = comparisons
            codes = [item["code"] for item in state["anomalies"]]
            expected_status = "pending_department_review" if expected["expected_department"] != "Document Review" else "manual_review"
            entry["checks"] = {
                "classification": state["document_type"] == expected["type"],
                "fields": all(item["correct"] for item in comparisons.values()),
                "evidence": not state["evidence_warnings"] and not state["validation_warnings"],
                "validation": state["validation_passed"] == expected["expected_validation"],
                "anomalies": set(codes) == set(expected["expected_anomalies"]),
                "routing": state["assigned_department"] == expected["expected_department"] and state["workflow_status"] == expected_status,
                "persistence": pipeline.repository.get_document(result["document_id"])["full_result"] == state,
                "mandatory_fields": all(state["extracted_fields"].get(field) for field in ValidationAgent.REQUIRED_FIELDS[expected["type"]]) == (expected["name"] != "contract_missing_date"),
                "cross_document": state["cross_document_status"] == "not_applicable",
            }
            if expected["name"] == "contract_missing_date":
                entry["checks"]["missing_date_not_invented"] = not state["extracted_fields"].get("effective_date")
            if expected["name"] == "contract_three_parties":
                entry["checks"]["all_parties_retained"] = len(state["contract_parties"]) == 3
            print(json.dumps({"fields": state["extracted_fields"], "validation": state["validation_passed"], "errors": state["validation_errors"], "anomalies": codes, "routing": state["workflow_status"], "checks": entry["checks"], "seconds": round(entry["seconds"], 3)}), flush=True)
        except Exception as error:
            entry.update(completed=False, seconds=time.perf_counter() - started, error_type=type(error).__name__, http_status=getattr(error, "status_code", None))
            print("FAILED: " + type(error).__name__, flush=True)
        report["documents"].append(entry)
        (output / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    complete = [entry for entry in report["documents"] if entry["completed"]]
    report["metrics"] = {"completed": len(complete), "all_checks_passed": sum(all(entry["checks"].values()) for entry in complete),
                         "mean_seconds": statistics.mean(entry["seconds"] for entry in complete) if complete else None}
    (output / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Saved " + str(output), flush=True)


if __name__ == "__main__":
    main()

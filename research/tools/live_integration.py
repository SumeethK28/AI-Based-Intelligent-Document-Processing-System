"""Run real OCR/Groq against existing samples, retaining safe audit results."""
from idp.security import INTERNAL
import json
import platform
import argparse
from datetime import datetime, timezone
from pathlib import Path

from idp.llm.provider import GroqProvider
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filenames", nargs="*")
    args = parser.parse_args()
    assert platform.python_version() == "3.14.6"
    provider = GroqProvider()
    pipeline = AgenticDocumentPipeline(llm=provider, _capability=INTERNAL)
    output = Path("results/live_integration_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"python": platform.python_version(), "model": provider.model,
              "provider": "GroqProvider (live API)", "tests": []}
    edges = pipeline.graph.get_graph().edges
    report["graph_edges"] = [[edge.source, edge.target] for edge in edges]
    with pipeline.repository.connect() as connection:
        report["initial_counts"] = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                                    for table in ("documents", "processing_runs")}
    paths = [Path("data/samples/cross_document/purchase_order_1023.pdf"),
             Path("data/samples/batch1-0004.jpg"),
             Path("data/samples/cross_document/invoice_matching.pdf"),
             Path("data/samples/cross_document/invoice_mismatch.pdf"),
             Path("data/samples/cross_document/invoice_unknown_po.pdf")]
    for path in paths:
        if args.filenames and path.name not in args.filenames:
            continue
        print(f"LIVE processing: {path.name}", flush=True)
        test = {"filename": path.name}
        try:
            result = pipeline.process(path, force_reprocess=True)
            test.update(result)
            stored = pipeline.repository.get_document(result["document_id"])
            test["persistence_matches"] = stored["full_result"] == result["state"]
            duplicate = pipeline.process(path)
            test["duplicate_reused"] = duplicate["duplicate"] and duplicate["state"] == result["state"]
            test["duplicate_run_id"] = duplicate["run_id"]
            print(json.dumps({k: result["state"].get(k) for k in (
                "document_type", "extracted_fields", "validation_passed", "validation_errors",
                "validation_warnings", "evidence_warnings", "anomalies", "cross_document_status",
                "workflow_status", "assigned_department", "agent_history")}, ensure_ascii=True), flush=True)
        except Exception as error:
            # Never emit raw provider exceptions or request headers containing credentials.
            test["error_type"] = type(error).__name__
            test["http_status"] = getattr(error, "status_code", None)
            response = getattr(error, "response", None)
            test["retry_after"] = response.headers.get("retry-after") if response is not None else None
            print(f"LIVE failed: {type(error).__name__}; HTTP {test['http_status']}", flush=True)
        report["tests"].append(test)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with pipeline.repository.connect() as connection:
        report["integrity_check"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
        report["final_counts"] = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                                  for table in ("documents", "processing_runs")}
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved live audit: {output}", flush=True)


if __name__ == "__main__":
    main()

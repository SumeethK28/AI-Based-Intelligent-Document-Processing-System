
import sys
from pathlib import Path

from idp.agents.graph import build_agent_graph
from idp.ocr.rapidocr_engine import RapidOCREngine
from idp.pipeline.document_pipeline import DocumentPipeline

import json
from idp.storage.repository import DocumentRepository

from idp.verification.cross_document import CrossDocumentVerifier
from idp.agents.routing_agent import WorkflowRoutingAgent

def main():

    if len(sys.argv) != 2:
        print(
            "Usage: uv run python scripts/run_agents.py "
            "path/to/document"
        )
        sys.exit(1)

    file_path = Path(sys.argv[1])

    if not file_path.is_file():
        raise FileNotFoundError(file_path)

    repository = DocumentRepository()
    existing_document = repository.check_duplicate(
        file_path
    )

    if existing_document is not None:

        print("\n=== DUPLICATE DOCUMENT DETECTED ===")

        print(
            "Original document ID:",
            existing_document["id"]
        )

        print(
            "Previously detected type:",
            existing_document["document_type"]
        )

        print(
            "Previous workflow status:",
            existing_document["workflow_status"]
        )

        # Record this repeat upload without rerunning Groq.
        previous_result = json.loads(
            existing_document["full_result"]
        )

        repeat = repository.save_processed_document(
            file_path=file_path,
            filename=file_path.name,
            final_state=previous_result,
        )

        print(
            "Duplicate processing run:",
            repeat["run_id"]
        )

        print(
            "No additional Groq requests were needed."
        )

        return
    # STEP 1: Run the existing baseline to obtain OCR text.
    # Existing classification/extraction may also run here,
    # but the agent graph will make its own decisions.
    baseline_pipeline = DocumentPipeline(
        ocr_engine=RapidOCREngine()
    )

    baseline_result = baseline_pipeline.process(
        file_path
    )

    # STEP 2: Build the agent graph.
    graph = build_agent_graph()

    # STEP 3: Prepare initial shared state.
    initial_state = {
        "filename": file_path.name,
        "ocr_text": baseline_result.ocr.full_text,
        "ocr_confidence": (
            baseline_result.ocr.average_confidence
        ),
        "agent_history": [],
        "errors": [],
    }

    # STEP 4: Execute the AI agents.
    final_state = graph.invoke(
        initial_state
    )

    # ====================================================
    # CROSS-DOCUMENT VERIFICATION
    # ====================================================

    verifier = CrossDocumentVerifier(
        repository=repository
    )

    cross_result = verifier.verify(
        final_state
    )

    final_state.update(cross_result)

    issues = cross_result["cross_document_issues"]

    # Verification issues are review signals.
    # They must affect the final workflow decision.

    if issues:

        final_state["anomalies"] = (
            final_state.get("anomalies", [])
            + issues
        )

        final_state["requires_review"] = True

        final_state["risk_level"] = (
            "medium"
        )

        # Re-evaluate routing using the updated risk/review
        # state before storing the final document.
        routing_agent = WorkflowRoutingAgent()

        routing_result = routing_agent.run(
            final_state
        )

        final_state.update(
            routing_result
        )

    final_state["agent_history"] = (
        final_state.get("agent_history", [])
        + ["cross_document_verification"]
    )

    print("\n=== CROSS-DOCUMENT VERIFICATION ===")

    print(
        "Status:",
        final_state["cross_document_status"]
    )

    print(
        "Matched PO ID:",
        final_state["matched_document_id"]
    )

    for issue in issues:
        print(
            f"[{issue['severity'].upper()}] "
            f"{issue['code']}: "
            f"{issue['description']}"
        )

    saved = repository.save_processed_document(
        file_path=file_path,
        filename=file_path.name,
        final_state=final_state,
    )

    print("\n=== DATABASE STORAGE ===")

    print(
        "Document ID:",
        saved["document_id"]
    )

    print(
        "Processing Run ID:",
        saved["run_id"]
    )

    print(
        "Duplicate:",
        saved["is_duplicate"]
    )

    # STEP 5: Print agent results.
    print("\n=== AI DOCUMENT CLASSIFICATION ===")
    print(
        "Document type:",
        final_state.get("document_type")
    )
    print(
        "Model confidence:",
        final_state.get(
            "classification_confidence"
        )
    )
    print(
        "Evidence:",
        final_state.get(
            "classification_evidence",
            []
        )
    )

    print("\n=== AI FIELD EXTRACTION ===")

    for field, value in final_state.get(
        "extracted_fields",
        {}
    ).items():
        print(f"{field}: {value}")

    print("\n=== EVIDENCE WARNINGS ===")
    print(
        final_state.get(
            "evidence_warnings",
            []
        )
    )

    print("\n=== VALIDATION AGENT ===")

    print(
        "Validation passed:",
        final_state.get("validation_passed"),
    )

    print(
        "Requires review:",
        final_state.get("requires_review"),
    )

    print("\nValidation errors:")

    for error in final_state.get(
        "validation_errors",
        [],
    ):
        print(f"  - {error}")

    print("\nValidation warnings:")

    for warning in final_state.get("validation_warnings",[],):
        print(f"  - {warning}")

    print("\n=== ANOMALY DETECTION AGENT ===")

    print("Risk level:",final_state.get("risk_level"))

    anomalies = final_state.get("anomalies", [])

    if anomalies:
        for anomaly in anomalies:
            print(
                f"[{anomaly['severity'].upper()}] "
                f"{anomaly['code']}: "
                f"{anomaly['description']}"
            )
    else:
        print("No anomalies detected by current rules.")


    print("\n=== WORKFLOW ROUTING AGENT ===")

    print(
        "Workflow status:",
        final_state.get("workflow_status")
    )

    print(
        "Assigned department:",
        final_state.get("assigned_department")
    )

    print(
        "Routing reason:",
        final_state.get("routing_reason")
    )

    print("\n=== COMPLETE AGENT HISTORY ===")

    print(
        " -> ".join(
            final_state.get("agent_history", [])
        )
    )


if __name__ == "__main__":
    main()

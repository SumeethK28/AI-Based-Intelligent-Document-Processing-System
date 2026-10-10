
import sys
from pathlib import Path

from idp.agents.graph import build_agent_graph
from idp.ocr.rapidocr_engine import RapidOCREngine
from idp.pipeline.document_pipeline import DocumentPipeline


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

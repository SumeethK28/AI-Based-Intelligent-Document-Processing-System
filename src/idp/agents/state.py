from typing import Any, TypedDict

class DocumentState(TypedDict, total=False):
    # Document identification
    document_id: str
    filename: str

    # Input from the existing OCR pipeline
    ocr_text: str
    ocr_confidence: float
    ocr_regions: list[dict[str, Any]]

    # Classification Agent
    document_type: str
    classification_confidence: float

    # Extraction Agent
    extracted_fields: dict[str, Any]
    extraction_confidence: float

    # Validation Agent
    validation_passed: bool
    validation_errors: list[str]

    # Anomaly Detection Agent
    anomalies: list[dict[str, Any]]
    risk_level: str

    # Workflow Routing Agent
    workflow_status: str
    assigned_department: str
    routing_reason: str

    # Execution metadata
    agent_history: list[str]
    errors: list[str]
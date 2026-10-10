
from typing import Any, TypedDict


class DocumentState(TypedDict, total=False):

    # Input
    document_id: str
    filename: str
    ocr_text: str
    ocr_confidence: float
    ocr_regions: list[dict[str, Any]]

    # Classification Agent
    document_type: str
    classification_confidence: float
    classification_evidence: list[str]

    # Extraction Agent
    extracted_fields: dict[str, Any]
    extraction_confidence: float
    field_evidence: dict[str, str]
    evidence_warnings: list[str]

    # Validation Agent
    validation_passed: bool
    validation_errors: list[str]

    # Anomaly Agent
    anomalies: list[dict[str, Any]]
    risk_level: str

    # Routing Agent
    workflow_status: str
    assigned_department: str
    routing_reason: str

    # Execution metadata
    agent_history: list[str]
    errors: list[str]

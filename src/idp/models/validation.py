from dataclasses import dataclass

@dataclass
class ValidationResult:
    is_valid: bool
    validation_score: float
    missing_fields: list[str]
    invalid_fields: list[str]
    warnings: list[str]
    requires_review: bool

from decimal import Decimal
from typing import Any

from idp.agents.state import DocumentState
from idp.agents.validation_agent import ValidationAgent


class AnomalyDetectionAgent:
    """
    Detects document-level inconsistencies.

    This is a rule-based anomaly detector,
    not a trained fraud detection model.
    """

    def __init__(self):
        self.validator = ValidationAgent()

        # Demo policy threshold, not a fraud statistic.
        self.large_amount_threshold = Decimal("100000")

    @staticmethod
    def normalize(value: Any) -> str:
        return " ".join(str(value or "").casefold().split())

    @staticmethod
    def anomaly(
        code: str,
        description: str,
        severity: str,
    ) -> dict[str, str]:
        return {
            "code": code,
            "description": description,
            "severity": severity,
        }

    def run(self, state: DocumentState) -> dict:

        fields = state.get("extracted_fields", {})
        document_type = state.get(
            "document_type", "unknown"
        )

        anomalies = []

        # =============================================
        # 1. EVIDENCE ANOMALIES
        # =============================================

        for warning in state.get(
            "evidence_warnings", []
        ):
            anomalies.append(
                self.anomaly(
                    code="UNVERIFIED_EVIDENCE",
                    description=warning,
                    severity="medium",
                )
            )

        # =============================================
        # 2. AMOUNT ANOMALIES
        # =============================================

        total_value = fields.get("total")

        if total_value:

            amount = self.validator.parse_amount(
                str(total_value)
            )

            if amount is not None:

                if amount < 0:
                    anomalies.append(
                        self.anomaly(
                            code="NEGATIVE_TOTAL",
                            description=(
                                "Document total is negative."
                            ),
                            severity="medium",
                        )
                    )

                if amount > self.large_amount_threshold:
                    anomalies.append(
                        self.anomaly(
                            code="LARGE_AMOUNT",
                            description=(
                                "Document total exceeds the "
                                "configured review threshold."
                            ),
                            severity="medium",
                        )
                    )

        # =============================================
        # 3. PARTY CONSISTENCY
        # =============================================

        if document_type == "invoice":

            seller = self.normalize(
                fields.get("seller")
            )

            client = self.normalize(
                fields.get("client")
            )

            if seller and client and seller == client:
                anomalies.append(
                    self.anomaly(
                        code="SAME_SELLER_CLIENT",
                        description=(
                            "Seller and client have identical "
                            "extracted names. Verify the parties."
                        ),
                        severity="medium",
                    )
                )

        elif document_type == "purchase_order":

            vendor = self.normalize(
                fields.get("vendor")
            )

            buyer = self.normalize(
                fields.get("buyer")
            )

            if vendor and buyer and vendor == buyer:
                anomalies.append(
                    self.anomaly(
                        code="SAME_VENDOR_BUYER",
                        description=(
                            "Vendor and buyer have identical "
                            "extracted names. Verify the parties."
                        ),
                        severity="medium",
                    )
                )

        # =============================================
        # 4. VALIDATION-RELATED RISK
        # =============================================

        if state.get("validation_errors"):
            anomalies.append(
                self.anomaly(
                    code="VALIDATION_FAILURE",
                    description=(
                        "One or more extracted fields failed "
                        "validation."
                    ),
                    severity="medium",
                )
            )

        # =============================================
        # 5. RISK CLASSIFICATION
        # =============================================

        severities = {
            item["severity"]
            for item in anomalies
        }

        if "high" in severities:
            risk_level = "high"

        elif "medium" in severities:
            risk_level = "medium"

        elif anomalies:
            risk_level = "low"

        else:
            risk_level = "low"

        return {
            "anomalies": anomalies,
            "risk_level": risk_level,
            "agent_history": (
                state.get("agent_history", [])
                + ["anomaly_agent"]
            ),
        }

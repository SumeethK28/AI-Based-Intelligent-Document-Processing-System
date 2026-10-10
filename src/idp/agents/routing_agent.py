
from idp.agents.state import DocumentState


class WorkflowRoutingAgent:

    DEPARTMENT_MAP = {
        "invoice": "Finance",
        "purchase_order": "Procurement",
        "receipt": "Expense Processing",
        "contract": "Legal",
    }

    def run(self, state: DocumentState) -> dict:

        document_type = state.get(
            "document_type", "unknown"
        )

        risk_level = state.get(
            "risk_level", "unknown"
        )

        validation_passed = state.get(
            "validation_passed", False
        )

        requires_review = state.get(
            "requires_review", True
        )

        # =============================================
        # 1. UNKNOWN DOCUMENT
        # =============================================

        if document_type not in self.DEPARTMENT_MAP:

            workflow_status = "unclassified_review"

            assigned_department = "Document Operations"

            routing_reason = (
                "The document type is unknown or unsupported."
            )

        # =============================================
        # 2. FAILED VALIDATION
        # =============================================

        elif not validation_passed or requires_review:

            workflow_status = "manual_review"

            assigned_department = "Document Review"

            routing_reason = (
                "Document validation failed or requires "
                "manual verification."
            )

        # =============================================
        # 3. HIGH RISK
        # =============================================

        elif risk_level == "high":

            workflow_status = "anomaly_review"

            assigned_department = "Risk Review"

            routing_reason = (
                "High-severity anomalies were detected."
            )

        # =============================================
        # 4. MEDIUM OR UNKNOWN RISK
        # =============================================

        elif risk_level != "low":

            workflow_status = "manual_review"

            assigned_department = "Document Review"

            routing_reason = (
                "Document has anomalies or an "
                "unresolved risk classification."
            )

        # =============================================
        # 5. NORMAL DEPARTMENT ROUTING
        # =============================================

        else:

            workflow_status = "pending_department_review"

            assigned_department = (
                self.DEPARTMENT_MAP[document_type]
            )

            routing_reason = (
                "Document passed preliminary checks "
                "and is queued for departmental processing."
            )

        return {
            "workflow_status": workflow_status,
            "assigned_department": assigned_department,
            "routing_reason": routing_reason,
            "agent_history": (
                state.get("agent_history", [])
                + ["routing_agent"]
            ),
        }

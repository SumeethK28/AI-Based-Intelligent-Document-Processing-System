from idp.verification.cross_document import CrossDocumentVerifier


class CrossDocumentAgent:
    """Apply verification and review signals before the graph routes a document."""

    def __init__(self, repository):
        self.verifier = CrossDocumentVerifier(repository)

    def run(self, state):
        result = self.verifier.verify(state)
        issues = result["cross_document_issues"]
        anomalies = state.get("anomalies", []) + issues
        levels = {item.get("severity", "low") for item in anomalies}
        levels.add(state.get("risk_level", "low"))
        result.update(
            anomalies=anomalies,
            risk_level="high" if "high" in levels else "medium" if "medium" in levels else "low",
            requires_review=state.get("requires_review", False) or bool(issues),
            agent_history=state.get("agent_history", []) + ["cross_document_verification"],
        )
        return result


from idp.agents.validation_agent import ValidationAgent
from idp.storage.repository import DocumentRepository
from idp.verification.cross_document import CrossDocumentVerifier


def main():

    repository = DocumentRepository()
    validator = ValidationAgent()
    verifier = CrossDocumentVerifier(repository)

    # =============================================
    # TEST 1: RETRIEVE STORED INVOICE
    # =============================================

    invoice = repository.get_document(3)

    assert invoice is not None, (
        "Invoice ID 3 was not found in SQLite."
    )

    state = invoice["full_result"]

    # =============================================
    # TEST 2: VALIDATE INVOICE AGAIN
    # =============================================

    print("\n=== INVOICE VALIDATION ===")

    validation_result = validator.run(state)

    print(
        "Validation passed:",
        validation_result["validation_passed"]
    )

    print(
        "Errors:",
        validation_result["validation_errors"]
    )

    print(
        "Warnings:",
        validation_result["validation_warnings"]
    )

    # =============================================
    # TEST 3: MATCHING INVOICE AND PO
    # =============================================

    print("\n=== MATCHING DOCUMENT TEST ===")

    result = verifier.verify(state)

    print(
        "Status:",
        result["cross_document_status"]
    )

    print(
        "Matched PO ID:",
        result["matched_document_id"]
    )

    for issue in result["cross_document_issues"]:
        print(issue)

    assert result["cross_document_status"] == "matched", (
        "Expected matching Invoice and Purchase Order."
    )

    # =============================================
    # TEST 4: AMOUNT MISMATCH
    # =============================================

    mismatch_state = {
        **state,
        "extracted_fields": {
            **state["extracted_fields"],
            "total": "INR 50000.00",
        },
    }

    print("\n=== AMOUNT MISMATCH TEST ===")

    mismatch_result = verifier.verify(
        mismatch_state
    )

    print(
        "Status:",
        mismatch_result["cross_document_status"]
    )

    for issue in mismatch_result["cross_document_issues"]:
        print(issue)

    assert mismatch_result["cross_document_status"] == "mismatch"

    assert any(
        issue["code"] == "TOTAL_MISMATCH"
        for issue in mismatch_result["cross_document_issues"]
    )

    print("\nAll cross-document tests passed.")


if __name__ == "__main__":
    main()

import argparse
from pathlib import Path

from idp.ocr.rapidocr_engine import RapidOCREngine
from idp.pipeline.document_pipeline import DocumentPipeline
from idp.utils.json_utils import save_dataclass_json


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Process a document using the "
            "Intelligent Document Processing pipeline."
        )
    )

    parser.add_argument("document", help="Path to the document to process")

    args = parser.parse_args()

    document_path = Path(args.document)

    print()
    print("=" * 60)
    print("AI-BASED INTELLIGENT DOCUMENT PROCESSING SYSTEM")
    print("=" * 60)

    print(f"\nDocument: {document_path.name}")

    print("\n[1/5] Loading document...")

    ocr_engine = RapidOCREngine()

    pipeline = DocumentPipeline(
        ocr_engine=ocr_engine
    )

    print("[2/5] Performing OCR...")
    print("[3/5] Classifying document...")
    print("[4/5] Extracting information...")
    print("[5/5] Validating extracted information...")

    result = pipeline.process(
        document_path
    )

    print()
    print("=" * 60)
    print("PROCESSING RESULT")
    print("=" * 60)

    print(
        f"\nDocument class: "
        f"{result.classification.document_class.value}"
    )

    print(
        f"Classification confidence: "
        f"{result.classification.confidence * 100:.2f}%"
    )

    print(
        f"OCR confidence: "
        f"{result.ocr.average_confidence * 100:.2f}%"
    )

    print(
        f"Pages processed: "
        f"{result.ocr.total_pages}"
    )

    print("\n--- Extracted Text ---\n")

    print(result.ocr.full_text)

    if result.extracted_data:

        print("\n--- Extracted Invoice Fields ---\n")

        invoice = result.extracted_data

        print(
            f"Invoice Number : "
            f"{invoice.invoice_number}"
        )

        print(
            f"Issue Date     : "
            f"{invoice.issue_date}"
        )

        print(
            f"Seller         : "
            f"{invoice.seller}"
        )

        print(
            f"Client         : "
            f"{invoice.client}"
        )

        print(
            f"Tax ID         : "
            f"{invoice.tax_id}"
        )

        print(
            f"IBAN           : "
            f"{invoice.iban}"
        )

        print(
            f"Total          : "
            f"{invoice.total}"
        )

    if result.validation:

        print("\n--- Validation ---\n")

        print(
            f"Valid: "
            f"{result.validation.is_valid}"
        )

        print(
            f"Completeness: "
            f"{result.validation.validation_score * 100:.2f}%"
        )

        if result.validation.missing_fields:
            print("Missing fields: " + ", ".join(result.validation.missing_fields))

        if result.validation.warnings:
            print("Warnings: " + ", ".join(result.validation.warnings))

    output_path = (
        Path("results")
        / "processed"
        / f"{document_path.stem}.json"
    )

    save_dataclass_json(result, output_path)

    print(
        f"\nResult saved to: "
        f"{output_path}"
    )

    print("\nProcessing completed.")


if __name__ == "__main__":
    main()
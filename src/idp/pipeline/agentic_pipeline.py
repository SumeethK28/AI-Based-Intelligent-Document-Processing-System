
from pathlib import Path
from typing import Any

from idp.agents.graph import build_agent_graph
from idp.ocr.rapidocr_engine import RapidOCREngine
from idp.pipeline.document_pipeline import DocumentPipeline
from idp.storage.repository import DocumentRepository

from dataclasses import asdict, is_dataclass

class AgenticDocumentPipeline:
    """
    Coordinates:
    - Exact duplicate detection
    - Existing ingestion and OCR
    - LangGraph workflow with verification before routing
    - Cross-document verification
    - Final workflow routing
    - SQLite persistence
    - Forced reprocessing
    """

    def __init__(self, database_path="data/idp.db", *, baseline=None, llm=None):

        self.baseline = baseline if baseline is not None else DocumentPipeline(
            ocr_engine=RapidOCREngine()
        )

        self.repository = DocumentRepository(database_path)
        self.graph = build_agent_graph(repository=self.repository, llm=llm)

    def process(
        self,
        file_path: str | Path,
        original_filename: str | None = None,
        force_reprocess: bool = False,
    ) -> dict[str, Any]:

        path = Path(file_path)
        filename = original_filename or path.name

        if not path.is_file():
            raise FileNotFoundError(path)

        # =============================================
        # STEP 1: CHECK FOR EXACT DUPLICATES
        # =============================================

        previous = self.repository.check_duplicate(
            path
        )

        if previous is not None and not force_reprocess:

            stored_document = self.repository.get_document(
                previous["id"]
            )

            if stored_document is None:
                raise ValueError(
                    "Duplicate lookup returned a missing record."
                )

            previous_state = stored_document["full_result"]

            run = self.repository.save_processed_document(
                file_path=path,
                filename=filename,
                final_state=previous_state,
            )

            return {
                "duplicate": True,
                "reprocessed": False,
                "document_id": run["document_id"],
                "run_id": run["run_id"],
                "state": previous_state,
                "message": (
                    "Exact duplicate detected. "
                    "Previously stored processing results "
                    "were reused without calling Groq."
                ),
            }

        # =============================================
        # STEP 2: DOCUMENT INGESTION AND OCR
        # =============================================

        # This currently also runs the baseline
        # classifier, extractor, and validator.
        # We will separate the OCR-only path in a
        # later refactor.

        baseline_result = self.baseline.process(
            path
        )

        # =============================================
        # STEP 3: PREPARE INITIAL AGENT STATE
        # =============================================

        # =============================================
        # PREPARE BASELINE EXTRACTION RESULTS
        # =============================================

        baseline_fields = {}

        if baseline_result.extracted_data is not None:

            extracted = baseline_result.extracted_data

            if is_dataclass(extracted):

                baseline_fields = asdict(extracted)

        # =============================================
        # INITIAL AGENT STATE
        # =============================================

        initial_state = {
            "filename": filename,
            "ocr_text": baseline_result.ocr.full_text,
            "ocr_confidence": (
                baseline_result.ocr.average_confidence
            ),
            "baseline_document_type": (
                baseline_result.classification.document_class.value
            ),
            "baseline_fields": baseline_fields,
            "agent_history": [],
            "errors": [],
        }

        # =============================================
        # STEP 4: EXECUTE AGENT WORKFLOW
        # =============================================

        state = self.graph.invoke(
            initial_state
        )

        # =============================================
        # STEP 6: SAVE NEW OR REPROCESSED DOCUMENT
        # =============================================

        if previous is not None and force_reprocess:

            saved = (
                self.repository.save_reprocessed_document(
                    file_path=path,
                    filename=filename,
                    final_state=state,
                )
            )

            message = (
                "Document reprocessed successfully. "
                "The latest AI results were saved."
            )

            reprocessed = True

        else:

            saved = (
                self.repository.save_processed_document(
                    file_path=path,
                    filename=filename,
                    final_state=state,
                )
            )

            message = (
                "Document processed and saved successfully."
            )

            reprocessed = False

        # =============================================
        # STEP 7: RETURN APPLICATION RESULT
        # =============================================

        return {
            "duplicate": False,
            "reprocessed": reprocessed,
            "document_id": saved["document_id"],
            "run_id": saved["run_id"],
            "state": state,
            "message": message,
        }

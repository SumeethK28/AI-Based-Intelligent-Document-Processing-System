
from pathlib import Path
from typing import Any
from time import perf_counter

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

    def __init__(self, database_path="data/idp.db", *, baseline=None, llm=None, session_token=None, _capability=None):
        self.repository = DocumentRepository(database_path, session_token=session_token, _capability=_capability)
        self.repository.access.intake()
        self.baseline = baseline if baseline is not None else DocumentPipeline(
            ocr_engine=RapidOCREngine()
        )

        # Deterministic matching/policy need organizational references. Writes and
        # returned duplicate data remain guarded by the employee repository.
        checks=self.repository
        if not self.repository.internal:
            from idp.security import INTERNAL
            checks=DocumentRepository(database_path,_capability=INTERNAL)
        self.graph = build_agent_graph(repository=checks, llm=llm)

    def process(
        self,
        file_path: str | Path,
        original_filename: str | None = None,
        force_reprocess: bool = False,
        operation_key: str | None = None,
        ai_consent: bool = False,
    ) -> dict[str, Any]:

        path = Path(file_path)
        principal = self.repository.access.intake(force=force_reprocess)
        if not self.repository.internal:
            if ai_consent is not True:
                raise ValueError('Explicit consent to external Groq processing is required.')
            from idp.batch.ingestion import inspect_file
            if not path.is_file() or path.stat().st_size>20*1024*1024:
                raise ValueError('Document exceeds safe file limits or is unavailable.')
            inspect_file(original_filename or path.name,path.read_bytes())
            from idp.security.auth import AuthService
            AuthService(self.repository).event('external_ai_processing','allowed','document',principal['id'])
        started = perf_counter()
        filename = original_filename or path.name

        if not path.is_file():
            raise FileNotFoundError(path)
        if operation_key:
            import json
            with self.repository._connect() as db:
                prior = db.execute('SELECT * FROM processing_runs WHERE operation_key=?', (operation_key,)).fetchone()
            if prior:
                document = self.repository.get_document(prior['document_id'])
                if document['file_hash'] != self.repository.calculate_hash(path):
                    raise ValueError('Processing identifier belongs to a different source.')
                return {'duplicate':bool(prior['is_duplicate']), 'reprocessed':force_reprocess,
                        'document_id':prior['document_id'], 'run_id':prior['id'],
                        'state':json.loads(prior['result_snapshot']), 'message':'Recovered committed processing result.'}

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
                operation_key=operation_key,
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
            'document_id': previous['id'] if previous else None,
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
        state['processing_duration_seconds'] = perf_counter() - started

        # =============================================
        # STEP 6: SAVE NEW OR REPROCESSED DOCUMENT
        # =============================================

        if previous is not None and force_reprocess:

            saved = (
                self.repository.save_reprocessed_document(
                    file_path=path,
                    filename=filename,
                    final_state=state,
                    operation_key=operation_key,
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
                    operation_key=operation_key,
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

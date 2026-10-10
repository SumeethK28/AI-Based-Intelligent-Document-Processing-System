
from pathlib import Path
from typing import Any

from idp.agents.graph import build_agent_graph
from idp.ocr.rapidocr_engine import RapidOCREngine
from idp.pipeline.document_pipeline import DocumentPipeline
from idp.storage.repository import DocumentRepository


class AgentDocumentService:

    def __init__(
        self,
        database_path: str | Path = "data/idp.db",
    ):

        self.repository = DocumentRepository(
            database_path=database_path
        )

        self.baseline_pipeline = DocumentPipeline(
            ocr_engine=RapidOCREngine()
        )

        self.graph = build_agent_graph()

    def process_document(
        self,
        file_path: str | Path,
    ) -> dict[str, Any]:

        file_path = Path(file_path)

        if not file_path.is_file():
            raise FileNotFoundError(file_path)

        # =============================================
        # STEP 1: FINGERPRINT
        # =============================================

        file_hash = (
            self.repository.calculate_hash(
                file_path
            )
        )

        # =============================================
        # STEP 2: DUPLICATE CHECK
        # =============================================

        existing = self.repository.find_by_hash(
            file_hash
        )

        if existing is not None:

            return {
                "is_duplicate": True,
                "document": existing,
                "state": None,
            }

        # =============================================
        # STEP 3: EXISTING OCR PIPELINE
        # =============================================

        baseline_result = (
            self.baseline_pipeline.process(
                file_path
            )
        )

        # =============================================
        # STEP 4: INITIAL AGENT STATE
        # =============================================

        initial_state = {
            "filename": file_path.name,
            "ocr_text": baseline_result.ocr.full_text,
            "ocr_confidence": (
                baseline_result.ocr.average_confidence
            ),
            "agent_history": [],
            "errors": [],
        }

        # =============================================
        # STEP 5: FIVE-AGENT WORKFLOW
        # =============================================

        final_state = self.graph.invoke(
            initial_state
        )

        # =============================================
        # STEP 6: SAVE RESULTS
        # =============================================

        saved_document = (
            self.repository.save_document(
                filename=file_path.name,
                file_hash=file_hash,
                state=final_state,
            )
        )

        return {
            "is_duplicate": False,
            "document": saved_document,
            "state": final_state,
        }

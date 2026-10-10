"""Compatibility facade for callers using the original document service."""
from pathlib import Path
from idp.pipeline.agentic_pipeline import AgenticDocumentPipeline


class AgentDocumentService:
    def __init__(self, database_path: str | Path = "data/idp.db", **kwargs):
        self.pipeline = AgenticDocumentPipeline(database_path, **kwargs)
        self.repository = self.pipeline.repository
        self.baseline_pipeline = self.pipeline.baseline
        self.graph = self.pipeline.graph

    def process_document(self, file_path: str | Path, force_reprocess=False):
        result = self.pipeline.process(file_path, force_reprocess=force_reprocess)
        return {
            "is_duplicate": result["duplicate"],
            "document": self.repository.get_document(result["document_id"]),
            "state": None if result["duplicate"] else result["state"],
            "reprocessed": result["reprocessed"],
        }

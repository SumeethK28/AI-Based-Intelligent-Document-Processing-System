from dataclasses import dataclass
from enum import Enum
from pathlib import Path

class DocumentType(Enum):
    IMAGE = "image"
    PDF = "pdf"

@dataclass
class Document:
    path: Path
    filename: str
    extension: str
    document_type: DocumentType
    size_bytes: int

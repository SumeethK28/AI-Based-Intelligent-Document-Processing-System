from pathlib import Path

from idp.models.document import Document, DocumentType


class DocumentLoader:

    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
    PDF_EXTENSIONS = {".pdf"}

    def load(self, file_path: str | Path) -> Document:

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found: {path}"
            )

        if not path.is_file():
            raise ValueError(
                f"Path is not a file: {path}"
            )

        extension = path.suffix.lower()

        if extension in self.IMAGE_EXTENSIONS:
            document_type = DocumentType.IMAGE

        elif extension in self.PDF_EXTENSIONS:
            document_type = DocumentType.PDF

        else:
            raise ValueError(
                f"Unsupported document format: {extension}"
            )

        size_bytes = path.stat().st_size

        return Document(
            path=path,
            filename=path.name,
            extension=extension,
            document_type=document_type,
            size_bytes=size_bytes,
        )
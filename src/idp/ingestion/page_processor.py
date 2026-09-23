from pathlib import Path

import cv2
import fitz
import numpy as np

from idp.models.document import Document, DocumentType
from idp.models.page import DocumentPage

class PageProcessor:

    def process(self, document: Document) -> list[DocumentPage]:

        if document.document_type == DocumentType.IMAGE:
            return self._process_image(document.path)

        if document.document_type == DocumentType.PDF:
            return self._process_pdf(document.path)

        raise ValueError(
            f"Unsupported document type: {document.document_type}"
        )

    def _process_image(self,image_path: Path) -> list[DocumentPage]:

        image = cv2.imread(str(image_path))

        if image is None:
            raise ValueError(f"Unable to read image: {image_path}")

        return [
            DocumentPage(
                page_number=1,
                image=image
            )
        ]

    def _process_pdf(self,pdf_path: Path) -> list[DocumentPage]:

        pages = []

        pdf_document = fitz.open(pdf_path)

        try:
            for page_index in range(len(pdf_document)):

                page = pdf_document.load_page(page_index)

                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    alpha=False
                )

                image = np.frombuffer(
                    pixmap.samples,
                    dtype=np.uint8
                )

                image = image.reshape(
                    pixmap.height,
                    pixmap.width,
                    pixmap.n
                )

                if pixmap.n == 3:
                    image = cv2.cvtColor(
                        image,
                        cv2.COLOR_RGB2BGR
                    )

                pages.append(
                    DocumentPage(
                        page_number=page_index + 1,
                        image=image
                    )
                )

        finally:
            pdf_document.close()

        return pages
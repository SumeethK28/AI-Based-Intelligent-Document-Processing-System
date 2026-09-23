import numpy as np
from rapidocr import RapidOCR

from idp.models.ocr import OCRRegion, OCRResult
from idp.ocr.base import BaseOCREngine


class RapidOCREngine(BaseOCREngine):

    def __init__(self):
        self.engine = RapidOCR()

    def process(self, image: np.ndarray, page_number: int) -> OCRResult:

        result = self.engine(image)

        regions = []

        if result is None:
            return OCRResult(
                page_number=page_number,
                full_text="",
                average_confidence=0.0,
                regions=[],
            )

        boxes = result.boxes
        texts = result.txts
        scores = result.scores

        if texts is None:
            return OCRResult(
                page_number=page_number,
                full_text="",
                average_confidence=0.0,
                regions=[],
            )

        for box, text, score in zip(boxes, texts, scores):

            region = OCRRegion(
                text=str(text),
                confidence=float(score),
                bounding_box=[
                    [float(x), float(y)]
                    for x, y in box
                ],
            )

            regions.append(region)

        full_text = "\n".join(region.text for region in regions)

        average_confidence = (
            sum(region.confidence for region in regions) / len(regions) if regions else 0.0
        )

        return OCRResult(page_number=page_number, full_text=full_text, average_confidence=average_confidence, regions=regions)
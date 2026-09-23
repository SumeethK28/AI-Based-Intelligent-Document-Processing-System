from abc import ABC, abstractmethod

import numpy as np

from idp.models.ocr import OCRResult


class BaseOCREngine(ABC):

    @abstractmethod
    def process(self, image: np.ndarray, page_number: int) -> OCRResult:
        pass
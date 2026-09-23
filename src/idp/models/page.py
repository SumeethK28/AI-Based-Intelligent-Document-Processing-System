from dataclasses import dataclass

import numpy as np


@dataclass
class DocumentPage:
    page_number: int
    image: np.ndarray
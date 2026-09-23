from dataclasses import dataclass


@dataclass
class OCRRegion:
    text: str
    confidence: float
    bounding_box: list[list[float]]


@dataclass
class OCRResult:
    page_number: int
    full_text: str
    average_confidence: float
    regions: list[OCRRegion]


@dataclass
class DocumentOCRResult:
    filename: str
    total_pages: int
    full_text: str
    average_confidence: float
    pages: list[OCRResult]
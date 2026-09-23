from idp.models.ocr import OCRRegion, OCRResult


class PaddleResultParser:

    def parse(self, raw_result: list, page_number: int) -> OCRResult:

        regions = []

        for detection in raw_result:

            bounding_box = detection[0]
            text = detection[1][0]
            confidence = float(detection[1][1])

            region = OCRRegion(text=text, confidence=confidence, bounding_box=bounding_box)

            regions.append(region)

        full_text = "\n".join(region.text for region in regions)

        if regions:
            average_confidence = (
                sum(region.confidence for region in regions) / len(regions)
            )
        else:
            average_confidence = 0.0

        return OCRResult(page_number=page_number, full_text=full_text, average_confidence=average_confidence, regions=regions)
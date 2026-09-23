import re

from idp.models.invoice import InvoiceData
from idp.models.ocr import OCRRegion


class InvoiceExtractor:
    def extract(self, text: str, regions: list[OCRRegion] | None = None) -> InvoiceData:

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        seller = None
        client = None

        # Prefer layout-aware extraction when
        # OCR bounding boxes are available.
        if regions:
            seller = self._extract_party_from_layout(regions, "seller:")

            client = self._extract_party_from_layout(regions, "client:")

        # Fall back to text-based extraction
        # if layout extraction fails.
        if seller is None:
            seller = self._extract_value_after_label(lines, "seller:")

        if client is None:
            client = self._extract_value_after_label(lines, "client:")

        return InvoiceData(
            invoice_number=self._extract_invoice_number(
                text
            ),
            issue_date=self._extract_date(
                text
            ),
            seller=seller,
            client=client,
            tax_id=self._extract_tax_id(
                text
            ),
            iban=self._extract_iban(
                text
            ),
            total=self._extract_total(
                lines
            ),
        )

    def _extract_party_from_layout(self, regions: list[OCRRegion], label: str) -> str | None:

        label_region = None

        # Locate the Seller: or Client: OCR region.
        for region in regions:

            if (region.text.strip().lower() == label.lower()):
                label_region = region
                break

        if label_region is None:
            return None

        label_box = label_region.bounding_box

        label_left = min(point[0] for point in label_box)

        label_right = max(point[0] for point in label_box)

        label_bottom = max(point[1] for point in label_box)

        label_center_x = (
            label_left + label_right
        ) / 2

        candidates = []

        # Find OCR regions located below and
        # approximately in the same column.
        for region in regions:

            if region is label_region:
                continue

            candidate_text = region.text.strip()

            if not candidate_text:
                continue

            # Labels should never become party names.
            if candidate_text.lower() in {"seller:", "client:"}:
                continue

            box = region.bounding_box

            region_left = min(point[0] for point in box)

            region_right = max(point[0] for point in box)

            region_top = min(point[1] for point in box)

            region_center_x = (
                region_left + region_right
            ) / 2

            vertical_distance = (
                region_top - label_bottom
            )

            horizontal_distance = abs(region_center_x - label_center_x)

            if (0 <= vertical_distance <= 150 and horizontal_distance <= 250):
                candidates.append(
                    (vertical_distance, horizontal_distance, candidate_text)
                )

        if not candidates:
            return None

        # Prefer the nearest region below the label.
        candidates.sort(
            key=lambda item: (item[0], item[1])
        )

        return candidates[0][2]

    def _extract_invoice_number(self, text: str) -> str | None:

        pattern = (
            r"invoice\s*(?:no|number)?\s*[:#]?\s*"
            r"([A-Za-z0-9\-]+)"
        )

        match = re.search(pattern, text, re.IGNORECASE)

        return (match.group(1) if match else None)

    def _extract_date(self, text: str) -> str | None:

        patterns = [
            r"\b\d{2}/\d{2}/\d{4}\b",
            r"\b\d{2}-\d{2}-\d{4}\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)

            if match:
                return match.group(0)

        return None

    def _extract_value_after_label(self, lines: list[str], label: str) -> str | None:

        for index, line in enumerate(lines):

            if line.lower() == label.lower():

                next_index = index + 1

                if next_index < len(lines):
                    return lines[next_index]

        return None

    def _extract_tax_id(self, text: str) -> str | None:

        pattern = (
            r"tax\s*(?:id|ld)\s*[:#]?\s*"
            r"([A-Za-z0-9\-]+)"
        )

        match = re.search(pattern, text, re.IGNORECASE)

        return (match.group(1) if match else None)

    def _extract_iban(self, text: str) -> str | None:

        pattern = (
            r"IBAN\s*[:#]?\s*"
            r"([A-Z]{2}[A-Z0-9]+)"
        )

        match = re.search(pattern, text, re.IGNORECASE)

        if not match:
            return None

        return match.group(1).upper()

    def _extract_total(self, lines: list[str]) -> str | None:
        for index, line in enumerate(lines):

            if line.lower() == "total":

                following_lines = lines[
                    index + 1:index + 4
                ]

                if following_lines:
                    return following_lines[-1]

        return None
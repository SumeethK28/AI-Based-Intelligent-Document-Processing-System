import re
from idp.models.invoice import InvoiceData


class InvoiceExtractor:
    def extract(self, text: str) -> InvoiceData:

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        return InvoiceData(
            invoice_number=self._extract_invoice_number(text),
            issue_date=self._extract_date(text),
            seller=self._extract_value_after_label(
                lines,
                "seller:"
            ),
            client=self._extract_value_after_label(
                lines,
                "client:"
            ),
            tax_id=self._extract_tax_id(text),
            iban=self._extract_iban(text),
            total=self._extract_total(lines),
        )

    def _extract_invoice_number( self, text: str) -> str | None:

        pattern = (
            r"invoice\s*(?:no|number)?\s*[:#]?\s*"
            r"([A-Za-z0-9\-]+)"
        )

        match = re.search(pattern, text, re.IGNORECASE)

        return match.group(1) if match else None

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

        return match.group(1) if match else None

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
import re

from idp.models.purchase_order import PurchaseOrderData


class PurchaseOrderExtractor:

    def extract(
        self,
        text: str
    ) -> PurchaseOrderData:

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        return PurchaseOrderData(
            po_number=self._extract_po_number(
                text,
                lines
            ),
            order_date=self._extract_order_date(
                text,
                lines
            ),
            vendor=self._extract_value_after_labels(
                lines,
                [
                    "vendor:",
                    "supplier:",
                    "store name:",
                ]
            ),
            bill_to=self._extract_value_after_labels(
                lines,
                [
                    "bill to:",
                    "billing address:",
                ]
            ),
            ship_to=self._extract_value_after_labels(
                lines,
                [
                    "ship to:",
                    "shipping address:",
                ]
            ),
            total=self._extract_total(
                lines
            ),
        )

    # ========================================================
    # PO NUMBER
    # ========================================================

    def _extract_po_number(
        self,
        text: str,
        lines: list[str]
    ) -> str | None:

        # Handles same-line formats:
        #
        # PO#: 10238-102
        # PO No: 10238-102
        # PO Number: 10238-102
        # Purchase Order Number: 10238-102

        patterns = [
            (
                r"\bPO\s*#\s*:\s*"
                r"([A-Za-z0-9\-_/]+)"
            ),
            (
                r"\bPO\s*(?:No|Number)\s*"
                r"[:#]?\s*"
                r"([A-Za-z0-9\-_/]+)"
            ),
            (
                r"Purchase\s+Order\s+"
                r"(?:No|Number)\s*"
                r"[:#]?\s*"
                r"([A-Za-z0-9\-_/]+)"
            ),
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:
                return match.group(1)

        # Handles OCR output such as:
        #
        # PO#:
        # 10238-102

        return self._extract_value_after_labels(
            lines,
            [
                "po#:",
                "po #:", 
                "po no:",
                "po number:",
                "purchase order no:",
                "purchase order number:",
            ]
        )


    # ========================================================
    # ORDER DATE
    # ========================================================

    def _extract_order_date(
        self,
        text: str,
        lines: list[str]
    ) -> str | None:

        # First try label-based extraction because OCR often
        # places the label and value on separate lines.

        value = self._extract_value_after_labels(
            lines,
            [
                "order date:",
                "order date",
            ]
        )

        if value:

            if self._looks_like_date(value):
                return value

        # Fallback for same-line date.

        patterns = [
            (
                r"order\s+date\s*[:#]?\s*"
                r"(\d{2}/\d{2}/\d{4})"
            ),
            (
                r"order\s+date\s*[:#]?\s*"
                r"(\d{2}-\d{2}-\d{4})"
            ),
            (
                r"order\s+date\s*[:#]?\s*"
                r"(\d{4}-\d{2}-\d{2})"
            ),
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:
                return match.group(1)

        return None


    # ========================================================
    # GENERIC LABEL/VALUE EXTRACTION
    # ========================================================

    def _extract_value_after_labels(
        self,
        lines: list[str],
        labels: list[str]
    ) -> str | None:

        normalized_labels = [
            label.lower().strip()
            for label in labels
        ]

        for index, line in enumerate(lines):

            normalized_line = (
                line.lower().strip()
            )

            for label in normalized_labels:

                # --------------------------------------------
                # CASE 1
                #
                # Store Name:
                # T-Shirt Dreams
                # --------------------------------------------

                if normalized_line == label:

                    if index + 1 < len(lines):

                        value = lines[
                            index + 1
                        ].strip()

                        if value:
                            return value


                # --------------------------------------------
                # CASE 2
                #
                # Ship To: John Doe
                # --------------------------------------------

                if normalized_line.startswith(
                    label
                ):

                    value = line[
                        len(label):
                    ].strip()

                    if value:
                        return value

        return None


    # ========================================================
    # TOTAL
    # ========================================================

    def _extract_total(
        self,
        lines: list[str]
    ) -> str | None:

        total_labels = [
            "grand total:",
            "grand total",
            "order total:",
            "order total",
            "total amount:",
            "total amount",
            "total:",
            "total",
        ]

        # Search from the bottom because totals usually occur
        # near the end of purchase orders.

        for index in range(
            len(lines) - 1,
            -1,
            -1
        ):

            line = lines[index]

            normalized_line = (
                line.lower().strip()
            )

            for label in total_labels:

                if normalized_line == label:

                    if index + 1 < len(lines):

                        return lines[
                            index + 1
                        ].strip()


                if normalized_line.startswith(
                    label
                ):

                    value = line[
                        len(label):
                    ].strip()

                    if value:
                        return value

        return None


    # ========================================================
    # DATE HELPER
    # ========================================================

    def _looks_like_date(
        self,
        value: str
    ) -> bool:

        patterns = [
            r"\d{2}/\d{2}/\d{4}",
            r"\d{2}-\d{2}-\d{4}",
            r"\d{4}-\d{2}-\d{2}",
        ]

        return any(
            re.fullmatch(
                pattern,
                value.strip()
            )
            for pattern in patterns
        )
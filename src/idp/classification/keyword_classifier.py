import re

from idp.models.classification import (
    ClassificationResult,
    DocumentClass,
)


class KeywordDocumentClassifier:

    KEYWORDS = {

        DocumentClass.INVOICE: {
            "invoice": 5,
            "invoice no": 5,
            "invoice number": 5,
            "seller": 3,
            "client": 3,
            "net worth": 2,
            "vat": 2,
            "iban": 3,
            "total": 1,
        },

        DocumentClass.RECEIPT: {
            "receipt": 5,
            "receipt no": 5,
            "cashier": 4,
            "amount paid": 4,
            "change": 3,
            "subtotal": 2,
            "payment": 2,
            "total": 1,
        },

        DocumentClass.PURCHASE_ORDER: {
            "purchase order": 8,
            "purchase order number": 8,
            "po number": 7,
            "po no": 7,
            "p.o. number": 7,
            "vendor": 4,
            "ship to": 4,
            "bill to": 4,
            "buyer": 3,
            "order date": 3,
            "delivery date": 2,
            "total": 1,
        },

        DocumentClass.CONTRACT: {
            "agreement": 5,
            "contract": 5,
            "parties": 4,
            "terms and conditions": 4,
            "signature": 3,
            "effective date": 2,
        },
    }

    def classify(
        self,
        text: str
    ) -> ClassificationResult:

        normalized_text = self._normalize_text(
            text
        )

        scores = {}
        matches_by_class = {}

        for document_class, keywords in (
            self.KEYWORDS.items()
        ):

            score = 0
            matched_keywords = []

            for keyword, weight in (
                keywords.items()
            ):

                if self._contains_keyword(
                    normalized_text,
                    keyword
                ):

                    score += weight

                    matched_keywords.append(
                        keyword
                    )

            scores[document_class] = score

            matches_by_class[
                document_class
            ] = matched_keywords

        best_class = max(
            scores,
            key=scores.get
        )

        best_score = scores[
            best_class
        ]

        if best_score == 0:

            return ClassificationResult(
                document_class=(
                    DocumentClass.UNKNOWN
                ),
                confidence=0.0,
                matched_keywords=[],
            )

        maximum_score = sum(
            self.KEYWORDS[
                best_class
            ].values()
        )

        confidence = min(
            best_score / maximum_score,
            1.0
        )

        return ClassificationResult(
            document_class=best_class,
            confidence=confidence,
            matched_keywords=(
                matches_by_class[
                    best_class
                ]
            ),
        )

    def _normalize_text(
        self,
        text: str
    ) -> str:

        text = text.lower()

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        return text.strip()

    def _contains_keyword(
        self,
        text: str,
        keyword: str
    ) -> bool:

        pattern = (
            r"\b"
            + re.escape(keyword.lower())
            + r"\b"
        )

        return bool(
            re.search(
                pattern,
                text
            )
        )
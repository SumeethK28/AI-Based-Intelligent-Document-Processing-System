from idp.models.classification import (ClassificationResult, DocumentClass)


class KeywordDocumentClassifier:

    KEYWORDS = {
        DocumentClass.INVOICE: {
            "invoice",
            "invoice no",
            "invoice number",
            "seller",
            "client",
            "net worth",
            "vat",
            "total",
        },

        DocumentClass.RECEIPT: {
            "receipt",
            "cashier",
            "subtotal",
            "payment",
            "change",
            "amount paid",
        },

        DocumentClass.PURCHASE_ORDER: {
            "purchase order",
            "po number",
            "po no",
            "ship to",
            "bill to",
            "vendor",
        },

        DocumentClass.CONTRACT: {
            "agreement",
            "contract",
            "party",
            "parties",
            "terms and conditions",
            "signature",
        },
    }

    def classify(self, text: str) -> ClassificationResult:

        normalized_text = text.lower()

        best_class = DocumentClass.UNKNOWN
        best_matches = []

        for document_class, keywords in self.KEYWORDS.items():

            matches = [
                keyword
                for keyword in keywords
                if keyword in normalized_text
            ]

            if len(matches) > len(best_matches):
                best_class = document_class
                best_matches = matches

        if not best_matches:
            return ClassificationResult(document_class=DocumentClass.UNKNOWN, confidence=0.0, matched_keywords=[])

        total_keywords = len(self.KEYWORDS[best_class])

        confidence = (
            len(best_matches) / total_keywords
        )

        return ClassificationResult(document_class=best_class, confidence=confidence, matched_keywords=best_matches)

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


CURRENCY_ALIASES = {
    "₹": "INR",
    "INR": "INR",
    "RS": "INR",
    "RS.": "INR",
    "$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
}


@dataclass(frozen=True)
class MoneyValue:
    amount: Decimal
    currency: str | None


def parse_money(value: str | None) -> MoneyValue | None:
    if value is None:
        return None

    text = str(value).strip().upper()

    if not text:
        return None

    # Match a currency prefix or suffix without
    # accidentally matching inside another word.
    token_pattern = (
        r"(?<![A-Z])(?:INR|USD|EUR|GBP|RS\.?)(?![A-Z])"
        r"|[₹$€£]"
    )

    tokens = re.findall(token_pattern, text)

    currencies = {
        CURRENCY_ALIASES[token]
        for token in tokens
    }

    # Mixed currency labels are ambiguous.
    if len(currencies) > 1:
        return None

    currency = next(iter(currencies), None)

    number = re.sub(token_pattern, "", text).strip()
    number = re.sub(r"\s+", "", number)

    # Example: 42,000.00
    if re.fullmatch(
        r"-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?",
        number,
    ):
        number = number.replace(",", "")

    # Example: 42.000,00
    elif re.fullmatch(
        r"-?\d{1,3}(?:\.\d{3})+,\d{2}",
        number,
    ):
        number = number.replace(".", "").replace(",", ".")

    # Example: 819,06
    elif re.fullmatch(r"-?\d+,\d{2}", number):
        number = number.replace(",", ".")

    # Example: 42000.00
    elif re.fullmatch(r"-?\d+(?:\.\d{1,2})?", number):
        pass

    else:
        return None

    try:
        amount = Decimal(number)
    except InvalidOperation:
        return None

    return MoneyValue(
        amount=amount,
        currency=currency,
    )

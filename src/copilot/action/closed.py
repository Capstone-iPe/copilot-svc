"""Closed answers the merchant may give for constrained fields."""

from __future__ import annotations

import re

# Mirrors onb.rules.verdict: permitted aliases, refused words, and common unlisted types.
_BUSINESS_PHRASES = (
    "restaurant",
    "cafe",
    "coffee shop",
    "dhaba",
    "grocery",
    "kirana",
    "retail",
    "hawala",
    "hundi",
    "forex",
    "money service",
    "money transfer",
    "remittance",
    "crypto",
    "bitcoin",
    "nft",
    "gambling",
    "betting",
    "satta",
    "matka",
    "casino",
    "salon",
    "gym",
    "garage",
    "clinic",
    "pharmacy",
    "hotel",
    "bar",
    "petrol",
    "liquor",
    "cloud kitchen",
    "food truck",
    "chit",
    "chit fund",
)
_PAYMENT_WORDS = (
    "upi",
    "card",
    "cards",
    "cash",
    "wallet",
    "wallets",
    "netbanking",
    "net banking",
    "neft",
    "rtgs",
    "imps",
    "bharatqr",
    "qr",
)
_YES = {"yes", "y", "true", "haan"}
_NO = {"no", "n", "false", "nahi"}

_BUSINESS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in sorted(_BUSINESS_PHRASES, key=len, reverse=True)) + r")\b",
    re.I,
)
_PAYMENT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in sorted(_PAYMENT_WORDS, key=len, reverse=True)) + r")\b",
    re.I,
)
# Cafe and dhaba are restaurant. Kirana is grocery. The same map ONB uses at the verdict.
_BUSINESS_CANON = {
    "restaurant": "restaurant",
    "cafe": "restaurant",
    "coffee shop": "restaurant",
    "dhaba": "restaurant",
    "grocery": "grocery",
    "kirana": "grocery",
    "retail": "retail",
}
_PAYMENT_CANON = {
    "upi": "UPI",
    "card": "cards",
    "cards": "cards",
    "cash": "cash",
    "wallet": "wallet",
    "wallets": "wallet",
    "netbanking": "netbanking",
    "net banking": "netbanking",
    "neft": "neft",
    "rtgs": "rtgs",
    "imps": "imps",
    "bharatqr": "bharatqr",
    "qr": "bharatqr",
}
_NEGATED = re.compile(
    r"\b(?:not|no|isn'?t|aren'?t|wasn'?t|weren'?t|nahi|nahin)\b(?:\s+(?:a|an|the|bhai))?\s*$",
    re.I,
)

CLOSED_FIELDS = frozenset({"business_type", "payment_methods", "stores_payer_phones"})


def list_value(field: str, text: str) -> str | None:
    """The closed-list value supported by a word in text. A negated word does not count."""
    if field == "business_type":
        phrases = _positive(text, _BUSINESS_RE)
        if not phrases:
            return None
        return _BUSINESS_CANON.get(phrases[-1], phrases[-1])
    if field == "payment_methods":
        labels = []
        for word in _positive(text, _PAYMENT_RE):
            label = _PAYMENT_CANON.get(word, word)
            if label not in labels:
                labels.append(label)
        return ", ".join(labels) if labels else None
    return None


def closed_error(field: str, value: str) -> str | None:
    """Refusal reason when the value is outside the closed set. None when it may be saved."""
    text = value.strip()
    if field == "stores_payer_phones":
        return None if _phone_token(text) is not None else "bad_phones"
    if field == "business_type":
        return None if list_value(field, text) else "bad_business_type"
    if field == "payment_methods":
        return None if list_value(field, text) else "bad_payment_methods"
    return None


def normalize_closed(field: str, value: str) -> str:
    """Store a closed answer as the list value. Phones stay yes or no, as typed."""
    text = value.strip()
    if field == "stores_payer_phones":
        if _phone_token(text) == "nahi":
            return "No"
        return text
    return list_value(field, text) or text


def _positive(text: str, pattern: re.Pattern[str]) -> list[str]:
    found = []
    previous = 0
    for match in pattern.finditer(text):
        before = text[previous:match.start()]
        after = text[match.end(): match.end() + 16]
        if _negated(before, after):
            previous = match.end()
            continue
        found.append(match.group(0).lower())
        previous = match.end()
    return found


def _negated(before: str, after: str) -> bool:
    if re.match(r"\s*(?:nahi|nahin)\b", after, re.I):
        return True
    if "," in before:
        before = before.rsplit(",", 1)[-1]
    return _NEGATED.search(before) is not None


def _phone_token(value: str) -> str | None:
    word = re.match(r"[a-z]+", value.strip().lower())
    if word is None:
        return None
    token = word.group(0)
    if token in _YES | _NO:
        return token
    return None

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

CLOSED_FIELDS = frozenset({"business_type", "payment_methods", "stores_payer_phones"})


def closed_error(field: str, value: str) -> str | None:
    """Refusal reason when the value is outside the closed set. None when it may be saved."""
    text = value.strip()
    if field == "stores_payer_phones":
        return None if _phone_token(text) is not None else "bad_phones"
    if field == "business_type":
        return None if _BUSINESS_RE.search(text) else "bad_business_type"
    if field == "payment_methods":
        return None if _PAYMENT_RE.search(text) else "bad_payment_methods"
    return None


def normalize_closed(field: str, value: str) -> str:
    """Store phones in a form ONB accepts. Other closed fields stay as typed."""
    text = value.strip()
    if field != "stores_payer_phones":
        return text
    if _phone_token(text) == "nahi":
        return "No"
    return text


def _phone_token(value: str) -> str | None:
    word = re.match(r"[a-z]+", value.strip().lower())
    if word is None:
        return None
    token = word.group(0)
    if token in _YES | _NO:
        return token
    return None

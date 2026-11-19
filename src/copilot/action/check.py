"""The checks in the plan, section 4.4. A failed act is not saved."""

from __future__ import annotations

import re

from copilot.action.closed import closed_error, normalize_closed
from copilot.words import EDIT_CUE

FIELDS = {
    "shop_name",
    "city",
    "business_type",
    "monthly_volume",
    "payment_methods",
    "stores_payer_phones",
    "note",
}
_SPEAK = {
    "why",
    "ask",
    "chitchat",
    "pause",
    "recap",
    "undo",
    "change_request",
    "confirm",
    "confirm_yes",
    "confirm_no",
    "submit",
    "missing",
    "upload",
    "review_id",
    "override",
    "readback",
    "other_shop",
    "out_of_scope",
    "refuse",
}
_PAYMENT = {
    "upi": "UPI",
    "card": "cards",
    "cards": "cards",
    "cash": "cash",
    "wallet": "wallet",
    "wallets": "wallet",
    "netbanking": "netbanking",
    "net banking": "netbanking",
    "bharatqr": "bharatqr",
    "qr": "bharatqr",
}
_BUSINESS = {
    "restaurant": "restaurant",
    "cafe": "cafe",
    "coffee shop": "cafe",
    "dhaba": "dhaba",
    "grocery": "grocery",
    "kirana": "kirana",
    "retail": "retail",
}
_FIELD_WORD = re.compile(
    r"\b(shop(?:'s)? name|legal name|company name|business name|the name|city|business type|volume|payment|phones?)\b",
    re.I,
)
_FIELD = {
    "shop name": "shop_name",
    "shop's name": "shop_name",
    "legal name": "shop_name",
    "company name": "shop_name",
    "business name": "shop_name",
    "the name": "shop_name",
    "city": "city",
    "business type": "business_type",
    "volume": "monthly_volume",
    "payment": "payment_methods",
    "phone": "stores_payer_phones",
    "phones": "stores_payer_phones",
}


def check_acts(acts: list[dict], line: str, *, held: bool) -> list[dict]:
    kept: list[dict] = []
    for act in acts:
        kind = str(act.get("type") or "")
        if kind in _SPEAK:
            kept.append(act)
            continue
        if kind not in {"answer", "correct"}:
            kept.append(act)
            continue
        if held:
            kept.append({"type": "refuse", "reason": "after_verdict"})
            continue
        field = str(act.get("field") or "")
        value = str(act.get("value_span") or "").strip()
        if field not in FIELDS or not value or not _in_line(value, line):
            continue
        if EDIT_CUE.search(value):
            kept.append(_change(line))
            continue
        if str(act.get("confidence") or "high") == "low":
            kept.append({"type": "confirm", "field": field, "value_span": value})
            continue
        canonical = _canonical(field, act.get("canonical"), line)
        if canonical == "other":
            kept.append({"type": "refuse", "reason": "bad_business_type"})
            continue
        if canonical:
            value = canonical
        else:
            bad = closed_error(field, value)
            if bad:
                kept.append({"type": "refuse", "reason": bad})
                continue
            value = normalize_closed(field, value)
        kept.append({**act, "field": field, "value_span": value})
    return kept


def _change(line: str) -> dict:
    match = _FIELD_WORD.search(line)
    field = _FIELD.get(match.group(1).lower()) if match else None
    act = {"type": "change_request"}
    if field:
        act["field"] = field
    return act


def _canonical(field: str, raw, line: str) -> str | None:
    if raw in (None, "", []):
        return None
    if field == "stores_payer_phones":
        token = str(raw).strip().lower()
        if token in {"yes", "y", "haan"} and re.search(r"\b(?:yes|haan)\b", line, re.I):
            return "Yes"
        if token in {"no", "n", "nahi"} and re.search(r"\b(?:no|nahi)\b", line, re.I):
            return "No"
        return None
    if field == "business_type":
        token = str(raw).strip().lower()
        if token == "other":
            return "other"
        label = _BUSINESS.get(token)
        if label and re.search(rf"\b{re.escape(token)}\b", line, re.I):
            return label
        return None
    if field == "payment_methods":
        items = [part.strip().lower() for part in str(raw).split(",") if part.strip()]
        kept = []
        for item in items:
            label = _PAYMENT.get(item)
            if not label:
                return None
            if re.search(rf"\bno\s+{re.escape(item)}\b", line, re.I):
                continue
            if not re.search(rf"\b{re.escape(item)}\b", line, re.I):
                return None
            if label not in kept:
                kept.append(label)
        return ", ".join(kept) if kept else None
    return None


def _in_line(span: str, line: str) -> bool:
    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().casefold()

    return norm(span) in norm(line)

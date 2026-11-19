"""The checks in the plan, section 4.4. A failed act is not saved."""

from __future__ import annotations

import re

from copilot.action.closed import CLOSED_FIELDS, closed_error, normalize_closed
from copilot.words import EDIT_CUE, FIELD_OF, FIELD_WORD

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


def check_acts(acts: list[dict], line: str, *, held: bool, pending=None) -> list[dict]:
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
        if field not in FIELDS:
            field = _fits_pending(pending, value, line)
            if field:
                act = {**act, "type": "answer", "field": field}
        if field not in FIELDS or not value or not _in_line(value, line):
            continue
        if EDIT_CUE.search(value) or _names_other(value, field):
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


def _fits_pending(pending, value: str, line: str) -> str:
    """An invented field name can still be the question on screen, when the word fits it."""
    if not isinstance(pending, dict) or pending.get("kind") != "field" or not value:
        return ""
    name = str(pending.get("name") or "")
    if name not in FIELDS:
        return ""
    if name in CLOSED_FIELDS:
        return name if closed_error(name, value) is None else ""
    if EDIT_CUE.search(line) or _names_other(line, name):
        return ""
    return name


def _names_other(value: str, field: str) -> bool:
    match = FIELD_WORD.search(value)
    named = FIELD_OF.get(match.group(1).lower()) if match else ""
    return bool(named) and named != field


def _change(line: str) -> dict:
    match = FIELD_WORD.search(line)
    field = FIELD_OF.get(match.group(1).lower()) if match else None
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

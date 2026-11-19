"""Drop an act whose value is not the merchant's own words."""

from __future__ import annotations

import re

from copilot.action.closed import closed_error, normalize_closed

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
        bad = closed_error(field, value)
        if bad:
            kept.append({"type": "refuse", "reason": bad})
            continue
        kept.append({**act, "field": field, "value_span": normalize_closed(field, value)})
    return kept


def _in_line(span: str, line: str) -> bool:
    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().casefold()

    return norm(span) in norm(line)

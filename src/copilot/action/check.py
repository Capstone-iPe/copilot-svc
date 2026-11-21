"""The checks in the plan, section 4.4. A failed act is not saved."""

from __future__ import annotations

import re

from copilot.action.closed import CLOSED_FIELDS, closed_error, list_value, normalize_closed
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
_POINTER = re.compile(r"\b(?:earlier|previous|first|original|before|opened|started)\b", re.I)
_FILLER = re.compile(
    r"\b(?:the|a|an|my|me|i|it|one|earlier|previous|first|original|spelling|selection|"
    r"answer|put|back|before|this|that|what|opened|with|started|same|as|please|"
    r"again|to|of|and|just|only|city|name|figure|volume|payment|type|phones?|typed)\b",
    re.I,
)
_STATED = re.compile(
    r"\b(?:is|are|to|as|be)\s+(?:actually\s+|just\s+|only\s+)?[\"']?"
    r"(.+?)"
    r"[\"']?(?=\s*,\s*(?:not|why|what|how|when|where|who|which)\b"
    r"|\s+not\b|\s+but\s+why\b|\s+please\b|[.?!]|$)",
    re.I,
)
_QUESTION_AFTER = re.compile(
    r",\s*(?:why|what|how|when|where|who|which)\b|\bbut\s+why\b",
    re.I,
)
_IN_CITY = re.compile(r"^(?P<name>.+?) in (?P<city>[A-Z][a-z]+(?: [A-Z][a-z]+)?)$")
_NOT_A_CITY = {"india"}
_CITY_AND_TYPE = re.compile(
    r"^(?P<city>[^,]+?),\s+and\s+(?P<tail>it(?:'s| is)\s+.+)$",
    re.I,
)
_NAME_SENTENCE = re.compile(
    r"\b(?:we|we're|we are|based|sorry|it's|it is|i'm|i am|the shop|my)\b",
    re.I,
)


def check_acts(
    acts: list[dict],
    line: str,
    *,
    held: bool,
    pending=None,
    earlier: dict[str, list[str]] | None = None,
    last_saved: str | None = None,
    awaiting: str | None = None,
) -> list[dict]:
    if _pure_history(line):
        return [_recall(line, earlier or {}, last_saved)]
    acts = _confirm_labels(acts, line, pending, awaiting)
    acts = _prefer_stated(acts, line)
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
        invented = field not in FIELDS
        if invented:
            field = _fits_pending(pending, value, line)
        field = _closed_pending(pending, field, value, line)
        waited = _awaited_field(awaiting, line, value)
        if waited:
            field = waited
            act = {**act, "type": "correct", "field": field}
        elif invented and field:
            act = {**act, "type": "answer", "field": field}
        elif field:
            act = {**act, "field": field}
        if field == "stores_payer_phones":
            answer = _yes_no(line)
            if answer:
                value = answer
        if field not in FIELDS or not value or not _in_line(value, line):
            continue
        if field == "shop_name" and _NAME_SENTENCE.search(value):
            continue
        if EDIT_CUE.search(value) or _names_other(value, field):
            kept.append(_change(line))
            continue
        if str(act.get("confidence") or "high") == "low":
            kept.append({"type": "confirm", "field": field, "value_span": value})
            continue
        if field in {"business_type", "payment_methods"}:
            if str(act.get("canonical") or "").strip().lower() == "other":
                kept.append({"type": "refuse", "reason": "bad_business_type"})
                continue
            picked = list_value(field, line)
            if not picked:
                reason = "bad_business_type" if field == "business_type" else "bad_payment_methods"
                kept.append({"type": "refuse", "reason": reason})
                continue
            value = picked
        else:
            canonical = _canonical(field, act.get("canonical"), line)
            if canonical:
                value = canonical
            else:
                bad = closed_error(field, value)
                if bad:
                    kept.append({"type": "refuse", "reason": bad})
                    continue
                value = normalize_closed(field, value)
        kept.append({**act, "field": field, "value_span": value, "said": str(act.get("value_span") or value)})
    if not held:
        kept = _pair(kept, line, pending)
    return _merge_payments(_with_question(kept, line))


def _confirm_labels(acts: list[dict], line: str, pending, awaiting: str | None) -> list[dict]:
    """confirm_yes and confirm_no count only while a confirmation is open."""
    waiting = awaiting or ""
    name = str(pending.get("name") or "") if isinstance(pending, dict) else ""
    kept = []
    for act in acts:
        kind = str(act.get("type") or "")
        if kind not in {"confirm_yes", "confirm_no"}:
            kept.append(act)
            continue
        if waiting.startswith("confirm:"):
            kept.append(act)
            continue
        if kind == "confirm_no" and waiting.startswith("value_for:"):
            kept.append(act)
            continue
        answer = _yes_no(line)
        if name == "stores_payer_phones" and answer:
            kept.append({
                "type": "answer",
                "field": "stores_payer_phones",
                "value_span": line.strip(),
                "canonical": answer,
            })
    return kept


def _yes_no(line: str) -> str | None:
    match = re.fullmatch(r"\s*(yes|no|haan|nahi)\s*[.!]?\s*", line, re.I)
    if not match:
        return None
    return "Yes" if match.group(1).lower() in {"yes", "haan"} else "No"


def _closed_pending(pending, field: str, value: str, line: str) -> str:
    """A short closed answer belongs to the question on screen, not the previous field."""
    if not isinstance(pending, dict) or pending.get("kind") != "field" or not value:
        return field
    name = str(pending.get("name") or "")
    if name not in CLOSED_FIELDS or name == field:
        return field
    if EDIT_CUE.search(line) or _names_other(line, name):
        return field
    if closed_error(name, value) is not None and not list_value(name, line):
        return field
    return name


def _awaited_field(awaiting: str | None, line: str, value: str) -> str:
    """A value after 'what should the shop name be?' fills that field."""
    if not awaiting or not awaiting.startswith("value_for:") or not value or _QUESTION_AFTER.search(line):
        return ""
    if re.search(r"\b(?:why|what|how|when|where|who|which)\b|\?", line, re.I):
        return ""
    wanted = awaiting.split(":", 1)[1]
    if wanted not in FIELDS or _names_other(line, wanted):
        return ""
    return wanted


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
    """Phones only. A yes or no counts when that word is in the line."""
    if raw in (None, "", []) or field != "stores_payer_phones":
        return None
    token = str(raw).strip().lower()
    if token in {"yes", "y", "haan"} and re.search(r"\b(?:yes|haan)\b", line, re.I):
        return "Yes"
    if token in {"no", "n", "nahi"} and re.search(r"\b(?:no|nahi)\b", line, re.I):
        return "No"
    return None


def _prefer_stated(acts: list[dict], line: str) -> list[dict]:
    """A line that already names the new value is a correction, not a prompt for it."""
    stated = _stated(line)
    if not stated:
        return acts
    wanted = stated["value_span"].casefold()
    field = stated["field"]
    has_save = False
    replace = False
    for act in acts:
        kind = str(act.get("type") or "")
        if kind == "change_request":
            replace = True
        if kind not in {"answer", "correct"}:
            continue
        has_save = True
        got = str(act.get("value_span") or "").strip().casefold()
        if act.get("field") != field or (wanted in got and got != wanted) or (wanted not in got and got not in wanted):
            replace = True
    if has_save and not replace:
        return acts
    kept = []
    used = False
    for act in acts:
        kind = str(act.get("type") or "")
        if kind in {"answer", "correct", "change_request"}:
            if not used:
                kept.append(stated)
                used = True
            continue
        kept.append(act)
    if not used:
        kept.insert(0, stated)
    return kept


def _stated(line: str) -> dict | None:
    match = FIELD_WORD.search(line)
    if not match:
        return None
    field = FIELD_OF.get(match.group(1).lower())
    if not field:
        return None
    found = _STATED.search(line[match.end():])
    if not found:
        return None
    value = found.group(1).strip(" \t\"'.,")
    if not value or re.match(r"not\b", value, re.I) or EDIT_CUE.search(value):
        return None
    if _names_other(value, field):
        return None
    return {"type": "correct", "field": field, "value_span": value}


def _pure_history(line: str) -> bool:
    """The line only points at an earlier answer. It is not a new value."""
    if _stated(line) or not _POINTER.search(line):
        return False
    rest = _FILLER.sub(" ", line)
    rest = re.sub(r"[^A-Za-z0-9]+", " ", rest).strip()
    return rest == ""


def _recall(line: str, earlier: dict[str, list[str]], last_saved: str | None) -> dict:
    field = _history_field(line, earlier, last_saved)
    if not field:
        return {"type": "change_request"}
    prior = earlier.get(field) or []
    if re.search(r"\b(?:first|original|opened|started)\b", line, re.I):
        value = prior[0] if prior else ""
    else:
        value = prior[-2] if len(prior) >= 2 else ""
    if not value:
        return {"type": "recall_miss", "field": field}
    return {"type": "correct", "field": field, "value_span": value}


def _history_field(line: str, earlier: dict[str, list[str]], last_saved: str | None) -> str:
    if re.search(r"\bspelling\b|\bname\b", line, re.I):
        return "shop_name"
    named = FIELD_WORD.search(line)
    if named:
        return FIELD_OF.get(named.group(1).lower(), "")
    if re.search(r"\b(?:figure|volume)\b", line, re.I):
        return "monthly_volume"
    if re.search(r"\b(?:selection|payment)\b", line, re.I):
        return "payment_methods"
    if last_saved and earlier.get(last_saved):
        return last_saved
    rich = [name for name, vals in earlier.items() if len(vals) >= 2]
    if len(rich) == 1:
        return rich[0]
    return ""


def _with_question(acts: list[dict], line: str) -> list[dict]:
    """A question after the new value stays a question."""
    if any(str(act.get("type") or "") in {"why", "ask"} for act in acts):
        return acts
    if _QUESTION_AFTER.search(line):
        return [*acts, {"type": "why"}]
    return acts


def _pair(acts: list[dict], line: str, pending) -> list[dict]:
    """A second answer in the same line is saved with the first."""
    name = pending.get("name") if isinstance(pending, dict) and pending.get("kind") == "field" else ""
    found = _IN_CITY.match(line.strip())
    city = found.group("city").strip() if found else ""
    if (
        found
        and name == "shop_name"
        and city.casefold() not in _NOT_A_CITY
        and not _NAME_SENTENCE.search(found.group("name"))
    ):
        shop = found.group("name").strip()
        acts = _use_value(acts, "shop_name", shop, line)
        return _add_if_missing(acts, "city", city, line)
    found = _CITY_AND_TYPE.match(line.strip())
    if found and name == "city":
        city = found.group("city").strip()
        kind = list_value("business_type", found.group("tail"))
        acts = _use_value(acts, "city", city, line)
        if kind:
            acts = _add_if_missing(acts, "business_type", kind, line, grounded=True)
    return acts


def _use_value(acts: list[dict], field: str, value: str, line: str) -> list[dict]:
    if not _in_line(value, line):
        return acts
    out = []
    seen = False
    for act in acts:
        if act.get("type") in {"answer", "correct"} and act.get("field") == field:
            seen = True
            current = str(act.get("value_span") or "")
            if value.casefold() != current.casefold() and value.casefold() in current.casefold():
                act = {**act, "value_span": value}
        out.append(act)
    if not seen:
        out.append({"type": "answer", "field": field, "value_span": value})
    return out


def _add_if_missing(acts: list[dict], field: str, value: str, line: str, *, grounded: bool = False) -> list[dict]:
    if not value or not (grounded or _in_line(value, line)):
        return acts
    if any(act.get("type") in {"answer", "correct"} and act.get("field") == field for act in acts):
        return acts
    return [*acts, {"type": "answer", "field": field, "value_span": value}]


def _merge_payments(acts: list[dict]) -> list[dict]:
    payments = [
        act
        for act in acts
        if act.get("type") in {"answer", "correct"} and act.get("field") == "payment_methods"
    ]
    if len(payments) < 2:
        return acts
    labels: list[str] = []
    for act in payments:
        for part in str(act.get("value_span") or "").split(","):
            part = part.strip()
            if part and part not in labels:
                labels.append(part)
    merged = {**payments[0], "value_span": ", ".join(labels)}
    out = []
    placed = False
    for act in acts:
        if act.get("type") in {"answer", "correct"} and act.get("field") == "payment_methods":
            if not placed:
                out.append(merged)
                placed = True
            continue
        out.append(act)
    return out


def _in_line(span: str, line: str) -> bool:
    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().casefold()

    return norm(span) in norm(line)

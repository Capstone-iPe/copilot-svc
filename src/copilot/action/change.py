"""A new value is taken from the merchant's own line."""

from __future__ import annotations

from pathlib import Path

from copilot.say.questions import QUESTIONS
from copilot.words import CHANGE_HINTS, FIELD_EQ, FILE_NAME, NEW_VALUE, SLOT_HINTS, VOLUME


def file_in(line: str) -> str | None:
    match = FILE_NAME.search(line)
    return Path(match.group(0)).name if match else None


def upload_slot(line: str, pending: dict | None, slots: dict[str, list[str]]) -> str | None:
    if pending and pending.get("kind") == "upload":
        return str(pending["name"])
    if pending:
        return None
    candidates = slots["open"] + slots["missing"]
    if len(candidates) == 1:
        return candidates[0]
    padded = f" {line.lower()} "
    hits = [slot for slot in candidates if any(hint in padded for hint in SLOT_HINTS.get(slot, ()))]
    return hits[0] if len(hits) == 1 else None


def resolve_change(line: str) -> dict | None:
    match = FIELD_EQ.match(line)
    if match and match.group(1) in QUESTIONS:
        return {"field": match.group(1), "value": match.group(2)}
    low = line.lower()
    fields = [field for field, hints in CHANGE_HINTS.items() if any(hint in low for hint in hints)]
    if not fields:
        return None
    field = fields[0]
    if field == "monthly_volume":
        figures = [item.group(0).strip() for item in VOLUME.finditer(line) if any(c.isdigit() for c in item.group(0))]
        return {"field": field, "value": figures[-1]} if figures else None
    value = NEW_VALUE.search(line)
    return {"field": field, "value": value.group(1).strip()} if value else None

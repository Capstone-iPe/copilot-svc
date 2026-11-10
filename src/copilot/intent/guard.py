"""Requests code refuses without asking the model."""

from __future__ import annotations

from copilot.words import DATA_FIELDS, DIGITS, OVERRIDE, READBACK, SENSITIVE


def guard_intent(line: str, pending: dict | None) -> str | None:
    if READBACK.search(line) and (DIGITS.search(line) or SENSITIVE.search(line)):
        return "readback"
    data_field = pending and pending.get("kind") == "field" and pending.get("name") in DATA_FIELDS
    if not data_field and OVERRIDE.search(line):
        return "override"
    return None

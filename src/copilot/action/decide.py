"""One intent becomes at most one tool call."""

from __future__ import annotations

import re

from copilot.action.change import file_in, resolve_change, upload_slot
from copilot.action.closed import closed_error, normalize_closed
from copilot.words import REFUSED_INTENTS

_PLURAL = re.compile(r"\b(?:these|them|those)\b", re.I)


def apply_decision(
    line: str,
    intent: str,
    pending: dict | None,
    held: bool,
    slots: dict[str, list[str]],
) -> dict:
    kind = pending.get("kind") if pending else None
    if intent == "why":
        return {"action": "why", "mode": "plain"}
    if intent == "ask":
        return {"action": "why", "mode": "free"}
    if intent in REFUSED_INTENTS:
        return {"action": "refuse", "reason": intent}
    if intent == "review_id":
        return {"action": "review"} if held else {"action": "refuse", "reason": "no_review_yet"}
    if intent == "submit":
        return _submit(held, pending)
    if intent == "change_answer":
        return _change(line, held)
    if intent == "missing":
        return _missing(line, pending, held, slots, kind)
    if intent == "upload" or (intent == "answer" and kind == "upload"):
        return _upload(line, pending, slots, kind)
    if intent == "answer" and kind == "field":
        field = str(pending["name"])
        value = line.strip()
        bad = closed_error(field, value)
        if bad:
            return {"action": "refuse", "reason": bad}
        return {"action": "save", "field": field, "value": normalize_closed(field, value)}
    return {"action": "again"}


def _submit(held: bool, pending: dict | None) -> dict:
    if held:
        return {"action": "review"}
    if pending and not _note_only(pending):
        return {"action": "refuse", "reason": "not_ready"}
    return {"action": "submit"}


def _note_only(pending: dict) -> bool:
    return pending.get("kind") == "field" and pending.get("name") == "note"


def _change(line: str, held: bool) -> dict:
    if held:
        return {"action": "refuse", "reason": "after_verdict"}
    change = resolve_change(line)
    if not change:
        return {"action": "refuse", "reason": "change_how"}
    bad = closed_error(change["field"], change["value"])
    if bad:
        return {"action": "refuse", "reason": bad}
    change["value"] = normalize_closed(change["field"], change["value"])
    return {"action": "save", **change}


def _missing(line: str, pending: dict | None, held: bool, slots: dict[str, list[str]], kind: str | None) -> dict:
    if _PLURAL.search(line) and slots["open"] and not held:
        return {"action": "missing", "slots": list(slots["open"])}
    if kind == "upload":
        return {"action": "missing", "slots": [str(pending["name"])]}
    if not pending and not held and slots["open"]:
        return {"action": "missing", "slots": list(slots["open"])}
    return {"action": "again"}


def _upload(line: str, pending: dict | None, slots: dict[str, list[str]], kind: str | None) -> dict:
    if kind == "field":
        return {"action": "again"}
    name = file_in(line)
    if not name:
        return {"action": "refuse", "reason": "no_file"}
    slot = upload_slot(line, pending, slots)
    if not slot:
        return {"action": "which", "slots": slots["open"] + slots["missing"]}
    return {"action": "file", "slot": slot, "file": name}

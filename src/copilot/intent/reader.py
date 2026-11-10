"""Guard, then a fixed command, then the model."""

from __future__ import annotations

import re

from copilot.intent.classifier import classify
from copilot.intent.commands import fast_intent
from copilot.intent.guard import guard_intent
from copilot.words import FILE_NAME, VOLUME

_ATTACHED = re.compile(r"\b(?:already\s+)?attach(?:ed)?\b", re.I)
_OTHER_SHOP = re.compile(
    r"\b(?:another|other|different)\s+shop\b|\bacross the street\b|\bstatus of\b",
    re.I,
)
_PLAIN_FIELDS = {"shop_name", "city", "business_type", "payment_methods", "stores_payer_phones"}


def read_intent(line: str, pending: dict | None, held: bool, complete) -> tuple[str, str]:
    guarded = guard_intent(line, pending)
    if guarded:
        return guarded, "guard"
    command = fast_intent(line)
    if command:
        return command, "command"
    settled = _settled(line, pending)
    if settled:
        return settled
    intent = classify(line, pending, held, complete)
    if intent:
        return intent, "model"
    return "", "fallback"


def _settled(line: str, pending: dict | None) -> tuple[str, str] | None:
    """A plain reply is stored. A question is not. A bare figure is the volume."""
    if pending and pending.get("kind") == "upload" and not FILE_NAME.search(line) and _ATTACHED.search(line):
        return "upload", "command"
    if _field(pending, "note"):
        return ("why", "note") if line.strip().endswith("?") else ("answer", "note")
    if _field(pending, "monthly_volume") and VOLUME.fullmatch(line.strip()):
        return "answer", "volume"
    if pending and pending.get("kind") == "field" and pending.get("name") in _PLAIN_FIELDS:
        if _OTHER_SHOP.search(line):
            return "other_shop", "field"
        if line.strip().endswith("?"):
            return "why", "field"
        return "answer", "field"
    return None


def _field(pending: dict | None, name: str) -> bool:
    return bool(pending and pending.get("kind") == "field" and pending.get("name") == name)

"""One merchant line becomes a list of acts. Code checks them before any save."""

from __future__ import annotations

import json
import re

from copilot.dialogue import DialogueState
from copilot.intent.commands import fast_intent
from copilot.intent.guard import guard_intent
from copilot.intent.reader import read_intent

_CHAT = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "hmm", "👍"}
_PAUSE = re.compile(r"^(?:wait|later)\b", re.I)
_UNDO = re.compile(r"^(?:go back|undo|that last one was wrong)\b", re.I)
_RECAP = re.compile(r"\b(?:what have i|show my answers)\b", re.I)
_CHANGE_ASK = re.compile(r"\bcan i change\b", re.I)
_SHOULD = re.compile(
    r"\b(shop name|legal name|company name|business name|the name|city|business type|volume|payment|phones?)\b"
    r".{0,40}?\b(?:should be|is)\s+(.+)$",
    re.I,
)
_CHANGE_TO = re.compile(
    r"\b(?:change|update)\b.{0,40}?\b(shop name|legal name|city|business type|volume|payment|phones?)\b"
    r".{0,20}?\b(?:to|is)\s+(.+)$",
    re.I,
)
_ITS_NOT = re.compile(r"\bit'?s\s+(.+?)\s+not\b", re.I)
_IN_CITY = re.compile(r"^(.+?)\s+in\s+([A-Za-z][\w .'-]+)$")
_BUT_WHY = re.compile(r"^(.+?)\s*,?\s+but\s+why\b", re.I)
_FIELD = {
    "shop name": "shop_name",
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

_ACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "acts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "field": {"type": ["string", "null"]},
                    "value_span": {"type": ["string", "null"]},
                },
                "required": ["type"],
            },
        }
    },
    "required": ["acts"],
}


class _NeedModel(Exception):
    pass


def _need_model(*_args, **_kwargs):
    raise _NeedModel


def read_acts(line, pending, held, snapshot, complete, dialogue: DialogueState) -> tuple[list[dict], str]:
    """Acts for one line. A settled answer never calls the model."""
    guarded = guard_intent(line, pending)
    if guarded:
        return [{"type": guarded}], "guard"
    command = fast_intent(line)
    if command:
        return [{"type": command}], "command"
    talk = _talk(line)
    if talk:
        return [{"type": talk}], "field"
    if dialogue.awaiting and dialogue.awaiting.startswith("value_for:") and not line.strip().endswith("?"):
        field = dialogue.awaiting.split(":", 1)[1]
        return [{"type": "correct", "field": field, "value_span": line.strip()}], "awaiting"
    coded = _code_acts(line, pending, snapshot, dialogue)
    if coded:
        return coded, "code"
    try:
        intent, source = read_intent(line, pending, held, _need_model)
    except _NeedModel:
        parsed = _model_acts(line, pending, snapshot, complete)
        if parsed:
            return parsed, "model"
        intent, source = read_intent(line, pending, held, complete)
    return [_as_act(intent, line, pending)], source


def _talk(line: str) -> str | None:
    low = line.strip().lower().rstrip("?.! ")
    if low in _CHAT:
        return "chitchat"
    if _PAUSE.match(line.strip()):
        return "pause"
    if _UNDO.match(line.strip()):
        return "undo"
    if _RECAP.search(low):
        return "recap"
    if _CHANGE_ASK.search(low):
        return "change_request"
    return None


def _code_acts(line, pending, _snapshot, dialogue: DialogueState) -> list[dict] | None:
    why = _BUT_WHY.match(line.strip())
    if why and pending and pending.get("kind") == "field":
        value = why.group(1).strip(" ,")
        return [
            {"type": "answer", "field": str(pending["name"]), "value_span": value},
            {"type": "why", "field": str(pending["name"])},
        ]
    named = _CHANGE_TO.search(line) or _SHOULD.search(line)
    if named:
        field = _FIELD.get(named.group(1).lower())
        value = named.group(2).strip(" .")
        if field and value:
            return [{"type": "correct", "field": field, "value_span": value}]
    swapped = _ITS_NOT.search(line)
    if swapped and dialogue.last_saved:
        value = swapped.group(1).strip(" .")
        if value:
            return [{"type": "correct", "field": dialogue.last_saved, "value_span": value}]
    pair = _IN_CITY.fullmatch(line.strip())
    if pair and pending and pending.get("name") == "shop_name":
        shop, city = pair.group(1).strip(), pair.group(2).strip()
        if shop and city:
            return [
                {"type": "answer", "field": "shop_name", "value_span": shop},
                {"type": "answer", "field": "city", "value_span": city},
            ]
    return None


def _as_act(intent: str, line: str, pending) -> dict:
    if intent == "answer" and pending and pending.get("kind") == "field":
        return {"type": "answer", "field": str(pending["name"]), "value_span": line.strip()}
    return {"type": intent or "again"}


def _model_acts(line, pending, snapshot, complete) -> list[dict] | None:
    pending_name = pending.get("name") if isinstance(pending, dict) else None
    stored = snapshot.get("answers") if isinstance(snapshot.get("answers"), dict) else {}
    payload = {"pending": pending_name, "stored": list(stored), "said": line}
    try:
        reply = complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Label the merchant line as JSON {\"acts\":[{\"type\",\"field\",\"value_span\"}]}. "
                        "type is answer, correct, why, ask, chitchat, pause, or submit. "
                        "value_span must be copied from the line. Do not invent a value."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            120,
            _ACTS_SCHEMA,
        )
    except Exception:
        return None
    if not reply:
        return None
    try:
        parsed = json.loads(reply)
    except json.JSONDecodeError:
        return None
    acts = parsed.get("acts") if isinstance(parsed, dict) else None
    if not isinstance(acts, list) or not acts:
        return None
    return [act for act in acts if isinstance(act, dict) and act.get("type")]

"""One merchant line becomes a list of acts. The model reads every line the fast path does not."""

from __future__ import annotations

import json
import logging
import re

from copilot.dialogue import DialogueState
from copilot.intent.classifier import stage
from copilot.intent.commands import fast_intent
from copilot.intent.guard import guard_intent
from copilot.intent.reader import read_intent
from copilot.prompts import READER_PROMPT, READER_SCHEMA
from copilot.say.questions import question_for
from copilot.words import (
    CHAT_WORDS,
    DIGITS,
    EDIT_CUE,
    FAST_CUE,
    FIELD_OF,
    FIELD_SYNONYM,
    FIELD_WORD,
    QUESTION_WORD,
    SMALL_TALK,
    THINK,
)

log = logging.getLogger("copilot")

_PAUSE = re.compile(r"^(?:wait|later)\b|\blet me check\b", re.I)
_YES = re.compile(r"^(?:yes|y|yeah|haan)\b", re.I)
_NO = re.compile(r"^(?:no|n|nahi)\b", re.I)
_RECAP = re.compile(
    r"\b(?:what have i|what values|what answers|show my|have you captured|captured so far)\b",
    re.I,
)
_NAME_IN_CITY = re.compile(r"^.+\s+in\s+\S.+$", re.I)
_SIDE = re.compile(r"\b(?:what|how|when|where|who|which)\b|\b(?:isn'?t|is not|not enough)\b", re.I)
_CANCEL = re.compile(
    r"^(?:never mind|forget it|no,? it'?s fine|leave it|don'?t change(?: it)?|cancel(?: that)?)$",
    re.I,
)


def read_acts(line, pending, held, snapshot, complete, dialogue: DialogueState) -> tuple[list[dict], str]:
    """Guard, exact command, narrow fast path, otherwise one model read."""
    guarded = guard_intent(line, pending)
    if guarded:
        log.info("model not called: guard %s", guarded)
        return [{"type": guarded}], "guard"
    command = fast_intent(line)
    if command:
        log.info("model not called: command %s", command)
        return [{"type": command}], "command"
    talk = _talk(line)
    if talk:
        log.info("model not called: %s", talk)
        return [{"type": talk}], "field"
    waiting = _waiting(line, dialogue)
    if waiting:
        log.info("model not called: waiting for %s", dialogue.awaiting)
        return waiting, "awaiting"
    if _fast_answer(line, pending):
        log.info("model not called: fast path")
        return [{"type": "answer", "field": str(pending["name"]), "value_span": line.strip(), "confidence": "high"}], "fast"
    parsed = _model_acts(line, pending, held, snapshot, complete, dialogue)
    if _RECAP.search(line):
        return [{"type": "recap"}], "model" if parsed is not None else "fallback"
    if parsed:
        return _aside(line, parsed), "model"
    if EDIT_CUE.search(line):
        return [_change(line)], "fallback"
    intent, source = read_intent(line, pending, held, complete)
    return [_as_act(intent, line, pending)], source


def _aside(line: str, acts: list[dict]) -> list[dict]:
    """A side question stays ask, even when the reader calls it why this field."""
    if not _SIDE.search(line):
        return acts
    kept = []
    for act in acts:
        if act.get("type") in {"why", "out_of_scope"}:
            kept.append({**act, "type": "ask", "field": None})
        else:
            kept.append(act)
    return kept


def _talk(line: str) -> str | None:
    low = line.strip().lower().rstrip("?.! ")
    if low in SMALL_TALK or low == "👍" or _chatty(line):
        return "chitchat"
    text = line.strip()
    if _PAUSE.search(text) and not EDIT_CUE.search(text) and not FIELD_WORD.search(text):
        return "pause"
    return None


def _waiting(line: str, dialogue: DialogueState) -> list[dict] | None:
    awaiting = dialogue.awaiting or ""
    if awaiting.startswith("confirm:"):
        if _YES.match(line.strip()):
            return [{"type": "confirm_yes"}]
        if _NO.match(line.strip()):
            return [{"type": "confirm_no"}]
        dialogue.awaiting = None
        dialogue.proposed = None
        return None
    if awaiting.startswith("value_for:") and _CANCEL.match(line.strip().rstrip("?.! ")):
        dialogue.awaiting = None
        return [{"type": "confirm_no"}]
    if awaiting.startswith("value_for:") and not line.strip().endswith("?") and not QUESTION_WORD.search(line):
        field = awaiting.split(":", 1)[1]
        return [{"type": "correct", "field": field, "value_span": line.strip(), "confidence": "high"}]
    if awaiting == "which_field":
        field = FIELD_OF.get(_field_word(line) or "")
        if field:
            return [{"type": "change_request", "field": field}]
    return None


def _fast_answer(line: str, pending) -> bool:
    """Section 4.5. Every condition must hold, or the line goes to the model."""
    if not pending or pending.get("kind") != "field":
        return False
    text = line.strip()
    words = text.split()
    if not words or len(words) > 5 or text.endswith("?"):
        return False
    if QUESTION_WORD.search(text) or FAST_CUE.search(text):
        return False
    low = text.lower().rstrip("?.! ")
    if low in SMALL_TALK or any(token in CHAT_WORDS for token in re.findall(r"[a-z']+", low)):
        return False
    name = str(pending.get("name") or "")
    for field, pattern in FIELD_SYNONYM:
        if field != name and pattern.search(text):
            return False
    if name == "shop_name" and _NAME_IN_CITY.match(text):
        return False
    return True


def _as_act(intent: str, line: str, pending) -> dict:
    if intent == "answer" and pending and pending.get("kind") == "field":
        return {"type": "answer", "field": str(pending["name"]), "value_span": line.strip(), "confidence": "high"}
    if intent == "change_answer":
        return [_change(line)][0]
    return {"type": intent or "again"}


def _change(line: str) -> dict:
    field = FIELD_OF.get(_field_word(line) or "")
    act = {"type": "change_request"}
    if field:
        act["field"] = field
    return act


def _chatty(line: str) -> bool:
    words = re.findall(r"[a-z']+", line.lower())
    return bool(words) and all(word in CHAT_WORDS for word in words)


def _field_word(line: str) -> str | None:
    match = FIELD_WORD.search(line)
    return match.group(1).lower() if match else None


def _model_acts(line, pending, held, snapshot, complete, dialogue: DialogueState) -> list[dict] | None:
    payload = {
        "stage": stage(pending, held),
        "question": question_for(pending) if pending else "",
        "stored": _redacted(snapshot),
        "awaiting": dialogue.awaiting,
        "last_saved": dialogue.last_saved,
        "recent": dialogue.recent,
        "said": line,
    }
    messages = [
        {"role": "system", "content": READER_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    for _ in range(2):
        try:
            reply = complete(messages, 180, READER_SCHEMA)
        except Exception:
            return None
        parsed = _parse(reply)
        if parsed:
            return parsed
        if not reply:
            return None
        messages = [
            *messages,
            {"role": "assistant", "content": reply},
            {"role": "user", "content": "Reply with one JSON object of acts and confidence."},
        ]
    return None


def _parse(reply: str | None) -> list[dict] | None:
    if not reply:
        return None
    text = THINK.sub("", reply).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    acts = parsed.get("acts")
    if not isinstance(acts, list) or not acts:
        return None
    confidence = parsed.get("confidence") if parsed.get("confidence") in {"high", "low"} else "low"
    kept = []
    for act in acts:
        if isinstance(act, dict) and act.get("type"):
            kept.append({**act, "confidence": act.get("confidence") or confidence})
    return kept or None


def _redacted(snapshot: dict) -> dict:
    stored = snapshot.get("answers") if isinstance(snapshot.get("answers"), dict) else {}
    return {str(key): DIGITS.sub("[number hidden]", str(value)) for key, value in stored.items() if value}

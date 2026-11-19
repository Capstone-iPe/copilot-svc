"""One merchant line becomes a list of acts. The model reads every line the guard does not."""

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
from copilot.words import DIGITS, EDIT_CUE, FIELD_OF, FIELD_WORD, THINK

log = logging.getLogger("copilot")

_RECAP = re.compile(
    r"\b(?:what have i|what values|what answers|show my|have you captured|captured so far)\b",
    re.I,
)
_SIDE = re.compile(r"\b(?:what|how|when|where|who|which)\b|\b(?:isn'?t|is not|not enough)\b", re.I)
_QUESTION = re.compile(r"\?|\b(?:why|what|how|when|where|who|which)\b", re.I)


def read_acts(line, pending, held, snapshot, complete, dialogue: DialogueState) -> tuple[list[dict], str]:
    """Guard, an exact command, otherwise one model read. Free text is not saved unread."""
    guarded = guard_intent(line, pending)
    if guarded:
        log.info("model not called: guard %s", guarded)
        return [{"type": guarded}], "guard"
    command = fast_intent(line)
    if command:
        log.info("model not called: command %s", command)
        return [{"type": command}], "command"
    parsed = _about_this_line(line, _model_acts(line, pending, held, snapshot, complete, dialogue))
    if _RECAP.search(line):
        return [{"type": "recap"}], "model" if parsed is not None else "fallback"
    if parsed:
        return _aside(line, parsed), "model"
    if EDIT_CUE.search(line) or _other_field(line, pending):
        return [_change(line)], "fallback"
    intent, source = read_intent(line, pending, held, complete)
    return [_as_act(intent, line, pending)], source


def _about_this_line(line: str, acts: list[dict] | None) -> list[dict] | None:
    """Drop an act whose words were copied from an earlier turn."""
    if not acts:
        return None
    kept = []
    for act in acts:
        span = str(act.get("value_span") or "").strip()
        kind = str(act.get("type") or "")
        if span and not _contains(span, line):
            log.info("model act ignored: %s is not in this line", span)
            continue
        if kind in {"why", "ask"} and not span and not _QUESTION.search(line):
            log.info("model act ignored: %s does not match this line", kind)
            continue
        kept.append(act)
    return kept or None


def _contains(span: str, line: str) -> bool:
    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().casefold()

    return norm(span) in norm(line)


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


def _other_field(line: str, pending) -> bool:
    named = FIELD_OF.get(_field_word(line) or "")
    current = str(pending.get("name") or "") if isinstance(pending, dict) else ""
    return bool(named) and named != current


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

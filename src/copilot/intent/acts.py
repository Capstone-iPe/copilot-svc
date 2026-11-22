"""One merchant line becomes a list of acts. The model reads every line the guard does not."""

from __future__ import annotations

import json
import logging
import re

from copilot.action.check import _NAME_SENTENCE
from copilot.dialogue import DialogueState
from copilot.intent.classifier import stage
from copilot.intent.commands import fast_intent
from copilot.intent.guard import guard_intent
from copilot.observability import complete_model
from copilot.prompts import READER_PROMPT, READER_SCHEMA
from copilot.say.questions import question_for
from copilot.words import DIGITS, EDIT_CUE, FIELD_OF, FIELD_WORD, THINK

log = logging.getLogger("copilot")

_RECAP = re.compile(
    r"\b(?:what have i|what values|what answers|show my|have you captured|captured so far)\b",
    re.I,
)
_SIDE = re.compile(r"\b(?:what|how|when|where|who|which)\b|\b(?:isn'?t|is not|not enough)\b", re.I)
_OTHER_QUESTION = re.compile(r"\b(?:what|how|when|where|who)\b|\b(?:isn'?t|is not|not enough)\b", re.I)
_QUESTION = re.compile(r"\?|\b(?:why|what|how|when|where|who|which)\b", re.I)
_CHATTER = re.compile(r"\b(?:hi|hello|hey|thanks|thank|ok|okay|hmm|wait|later)\b", re.I)


_DOC_CHANGE_PATTERNS = {
    "business_registration": re.compile(r"\b(?:(?:change|update|replace)\s+(?:the\s+)?)?(?:business\s+registration|registration\s+certificate)\b", re.I),
    "bank_proof": re.compile(r"\b(?:(?:change|update|replace)\s+(?:the\s+)?)?bank\s*(?:proof|statement|letter|passbook)\b", re.I),
    "owner_id": re.compile(r"\b(?:(?:change|update|replace)\s+(?:the\s+)?)?(?:owner'?s?\s+(?:government\s+)?id|government\s+id)\b", re.I),
    "shopfront_photo": re.compile(r"\b(?:(?:change|update|replace)\s+(?:the\s+)?)?(?:shopfront|front\s+photo)\b", re.I),
    "dpa_addendum": re.compile(r"\b(?:(?:change|update|replace)\s+(?:the\s+)?)?(?:data\s+processing\s+)?(?:addendum|dpa)\b", re.I),
}


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
    is_change = bool(
        re.search(r"\b(?:change|update|replace)\b", line, re.I)
        or (dialogue.awaiting in {"which_field", "change"})
    )
    if is_change:
        for slot, rx in _DOC_CHANGE_PATTERNS.items():
            if rx.search(line):
                log.info("model not called: doc change for %s", slot)
                return [{"type": "change_doc", "slot": slot}], "code"
    raw = _model_acts(line, pending, held, snapshot, complete, dialogue)
    parsed = _about_this_line(line, raw)
    if _RECAP.search(line):
        return [{"type": "recap"}], "model" if parsed is not None else "fallback"
    if parsed:
        return _aside(line, parsed, pending), "model"
    if EDIT_CUE.search(line) or _other_field(line, pending):
        return [_change(line)], "fallback"
    name = str(pending.get("name") or "") if isinstance(pending, dict) and pending.get("kind") == "field" else ""
    if name == "city" and _NAME_SENTENCE.search(line):
        return [{"type": "again"}], "fallback"
    if name and not _CHATTER.search(line) and not _QUESTION.search(line):
        return [{"type": "answer", "field": name, "value_span": line.strip(), "confidence": "high"}], "fallback"
    return [{"type": "again"}], "fallback"


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


def _aside(line: str, acts: list[dict], pending) -> list[dict]:
    """A side question stays ask. Why this field stays why when the line is about that field."""
    if not _SIDE.search(line):
        return acts
    current = str(pending.get("name") or "") if isinstance(pending, dict) else ""
    other = bool(_OTHER_QUESTION.search(line) or _other_field(line, pending))
    kept = []
    for act in acts:
        field = act.get("field")
        if act.get("type") in {"why", "out_of_scope"} and (other or not field or field != current):
            kept.append({**act, "type": "ask", "field": None})
        else:
            kept.append(act)
    return kept


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
            reply = complete_model("act-interpretation", complete, messages, 180, READER_SCHEMA)
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

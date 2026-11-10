"""One model call names the intent. One retry when the reply is not a label."""

from __future__ import annotations

import json
import logging
import re

from copilot.prompts import CLASSIFIER_PROMPT, FEW_SHOT, INTENT_SCHEMA, turn_json
from copilot.say.questions import QUESTIONS, UPLOADS
from copilot.words import INTENTS, THINK

log = logging.getLogger("copilot")


def stage(pending: dict | None, held: bool) -> str:
    if pending:
        return "upload" if pending.get("kind") == "upload" else "field"
    return "after_verdict" if held else "review"


def asked(pending: dict | None, held: bool) -> str:
    if pending:
        from copilot.say.questions import question_for

        return question_for(pending)
    return "" if held else "Submit the application?"


def parse_intent(reply: str | None) -> str | None:
    if not reply:
        return None
    text = THINK.sub("", reply).strip()
    for match in re.finditer(r"\{[^{}]*\}", text):
        parsed = _load(match.group(0))
        if isinstance(parsed, dict) and parsed.get("intent") in INTENTS:
            return str(parsed["intent"])
    word = text.strip().strip("\"'").lower()
    return word if word in INTENTS else None


def _load(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def few_shot_messages() -> list[dict]:
    messages = []
    for shot_stage, field, said, intent in FEW_SHOT:
        question = _shot_question(shot_stage, field)
        messages.append({"role": "user", "content": turn_json(shot_stage, question, said)})
        messages.append({"role": "assistant", "content": json.dumps({"intent": intent})})
    return messages


def _shot_question(shot_stage: str, field: str) -> str:
    if shot_stage == "upload":
        return UPLOADS[field]
    if shot_stage == "field":
        return QUESTIONS[field]
    return "Submit the application?" if shot_stage == "review" else ""


def classify(line: str, pending: dict | None, held: bool, complete) -> str | None:
    messages = [
        {"role": "system", "content": CLASSIFIER_PROMPT},
        *few_shot_messages(),
        {"role": "user", "content": turn_json(stage(pending, held), asked(pending, held), line)},
    ]
    for _ in range(2):
        reply = complete(messages, 24, INTENT_SCHEMA)
        if reply is None:
            return None
        intent = parse_intent(reply)
        if intent:
            return intent
        log.info("model reply was not a label")
        messages = [
            *messages,
            {"role": "assistant", "content": reply},
            {"role": "user", "content": 'Reply with one JSON object, such as {"intent": "answer"}.'},
        ]
    return None

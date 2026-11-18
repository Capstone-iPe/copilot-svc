"""The fixed commands from the help text."""

from __future__ import annotations

from copilot.say.questions import QUESTIONS
from copilot.words import CLARIFY_LINE, FIELD_EQ, FILE_NAME, MISSING_LINE


def fast_intent(line: str) -> str | None:
    low = line.strip().lower().rstrip("?.! ")
    if low in {"why", "but why"}:
        return "why"
    if CLARIFY_LINE.match(line.strip().rstrip("?.! ")):
        return "why"
    if low == "submit":
        return "submit"
    if low in {"review", "review id"}:
        return "review_id"
    match = FIELD_EQ.match(line)
    if match and match.group(1) in QUESTIONS:
        return "change_answer"
    if FILE_NAME.fullmatch(line.strip()):
        return "upload"
    if MISSING_LINE.match(low):
        return "missing"
    return None

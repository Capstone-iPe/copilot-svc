"""A tool result becomes one sentence. No model in this path."""

from __future__ import annotations

from copilot.say.questions import slot_list
from copilot.say.verdict import verdict_reply
from copilot.words import SLOT_WORDS


def file_sentence(slot: str, facts: dict) -> str:
    words = SLOT_WORDS.get(slot, slot)
    state = facts.get("state")
    if state == "accepted":
        return f"The {words} is accepted."
    if state == "missing":
        return f"Noted. The {words} stays missing."
    reason = facts.get("reason") or facts.get("reason_code")
    because = f" ({reason})" if reason else ""
    return f"The {words} was not accepted{because}. The same slot stays open. ONB-POL-001 §2."


_ONB_ERRORS = {
    "phones_not_yes_or_no": "Please answer yes or no.",
    "volume_unreadable": "Please give the monthly volume in digits, such as ₹12,00,000 or 12 lakh.",
    "empty_answer": "That answer was empty, so it was not stored.",
}


def result_reply(action: dict, results: list[dict], answers: dict) -> tuple[str, dict | None]:
    """The fixed reply for a tool result, and the verdict when ONB returned one."""
    errors = [str(result["error"]) for result in results if result.get("error")]
    if errors:
        known = [_ONB_ERRORS[code] for code in errors if code in _ONB_ERRORS]
        if known:
            return " ".join(known), None
        head = "The application was not submitted" if action["action"] == "submit" else "That was not stored"
        return f"{head} ({'; '.join(errors)}).", None
    parts = _parts(action, results)
    verdict = next((found for found in map(_verdict_in, results) if found), None)
    if verdict:
        parts.append(verdict_reply(verdict, answers))
    return " ".join(parts), verdict


def _parts(action: dict, results: list[dict]) -> list[str]:
    if action["action"] == "save":
        return ["Saved."]
    if action["action"] == "file":
        return [file_sentence(action["slot"], results[0])]
    if action["action"] == "missing":
        return [f"Noted. These stay missing: {slot_list(action['slots'])}."]
    return []


def _verdict_in(result: dict) -> dict | None:
    if isinstance(result.get("verdict"), dict):
        return result["verdict"]
    return result if "outcome" in result else None

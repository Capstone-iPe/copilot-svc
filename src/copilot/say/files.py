"""A tool result becomes one sentence. No model in this path."""

from __future__ import annotations

from copilot.say.questions import slot_list
from copilot.say.verdict import verdict_reply
from copilot.words import SLOT_WORDS


_REASON_EXPLANATION = {
    "FORMAT_UNSUPPORTED": "that file format is not supported; please upload a PDF, JPG, or PNG",
    "format": "that file format is not supported; please upload a PDF, JPG, or PNG",
    "FILE_UNREADABLE": "that file could not be read or is corrupted/password-protected",
    "unreadable": "that file could not be read or is corrupted/password-protected",
    "PHOTO_TOO_OLD": "that photo is older than 90 days on the day of submit",
    "too_old": "that photo is older than 90 days on the day of submit",
    "WRONG_DOCUMENT": "that document does not match what is required for this slot",
    "wrong_document": "that document does not match what is required for this slot",
    "NAME_MISMATCH": "the name on the document does not match the shop's legal name",
    "not_legal_name": "the name on the document does not match the shop's legal name",
    "NOT_SHOPFRONT": "that photo does not show the shopfront",
    "not_shopfront": "that photo does not show the shopfront",
    "UNSIGNED": "the addendum must be signed",
    "unsigned": "the addendum must be signed",
    "duplicate_file": "the same file cannot be used for two different slots",
    "rejected": "that document does not meet the requirements",
}


def file_sentence(slot: str, facts: dict) -> str:
    words = SLOT_WORDS.get(slot, slot)
    state = facts.get("state")
    evidence = facts.get("evidence") if isinstance(facts.get("evidence"), dict) else {}
    evidence_reason = evidence.get("reason")
    if state == "accepted":
        if evidence_reason:
            return f"The {words} is accepted: {evidence_reason}"
        return f"The {words} is accepted."
    if state == "missing":
        return f"Noted. The {words} stays missing."
    if evidence_reason:
        because = f": {evidence_reason}"
    else:
        raw_reason = facts.get("reason") or facts.get("reason_code")
        explanation = _REASON_EXPLANATION.get(raw_reason)
        if explanation:
            because = f": {explanation}"
        elif raw_reason:
            because = f" ({raw_reason})"
        else:
            because = ""
    return f"The {words} was not accepted{because}. The same slot stays open. ONB-POL-001 §2."


_FIELD_LABEL = {
    "shop_name": "shop name",
    "city": "city",
    "business_type": "business type",
    "monthly_volume": "monthly volume",
    "payment_methods": "payment methods",
    "stores_payer_phones": "payer phones",
    "note": "note",
}
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
        value = str(action.get("shown") or action.get("value") or "").strip()
        if action.get("correct"):
            label = _FIELD_LABEL.get(str(action.get("field") or ""), "answer")
            return [f"No problem, I've updated the {label} to {value}."]
        return [f"Got it, {value}."] if value else ["Got it."]
    if action["action"] == "file":
        return [file_sentence(action["slot"], results[0])]
    if action["action"] == "missing":
        return [f"Noted. These stay missing: {slot_list(action['slots'])}."]
    return []


def _verdict_in(result: dict) -> dict | None:
    if isinstance(result.get("verdict"), dict):
        return result["verdict"]
    return result if "outcome" in result else None

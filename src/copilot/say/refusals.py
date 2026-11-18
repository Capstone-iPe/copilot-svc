"""Fixed refusals. The model does not write these."""

from __future__ import annotations

from copilot.action.change import resolve_change
from copilot.words import ASSIGNEE_WORDS

_LINES = {
    "readback": "I can't repeat identity, account, or phone numbers in the chat, including the last four digits. ONB-POL-004.",
    "other_shop": "This chat is only about the shop in this application. ONB-POL-004 §5.",
    "out_of_scope": "The onboarding policies do not state that, so I won't give a figure. ONB-POL-004 §5.",
    "no_file": "No file came through. Saying it is attached does not count. ONB-POL-001 §2.",
    "not_ready": "Submit comes after the last question.",
    "no_review_yet": "No review is open yet. A review opens only after you submit.",
    "change_how": "To change an answer, type the field and the new value, such as city=Pune.",
    "bad_phones": "Please answer yes or no.",
    "bad_business_type": (
        "Please name the kind of shop, such as restaurant, grocery, retail, "
        "or another clear type (cafe, kirana, salon, gym)."
    ),
    "bad_payment_methods": "Please name the methods, such as UPI, cards, cash, or wallet.",
}


def refusal(reason: str, verdict: dict | None, line: str = "") -> str:
    if reason == "override":
        return _override(verdict)
    if reason == "after_verdict":
        return _after_verdict(verdict, line)
    return _LINES.get(reason, "")


def _override(verdict: dict | None) -> str:
    if verdict and verdict.get("review_id"):
        tail = f"Review {verdict['review_id']} is unchanged."
    elif verdict:
        tail = "There is still no review id."
    else:
        tail = "I review the application only after you submit. A person at iPe activates, outside this chat."
    return (
        "I can't activate the shop, waive a document, or change the rules from a chat message or a draft. "
        f"{tail} The shop is not live. ONB-POL-001 §4. ONB-POL-003 §3. ONB-POL-005."
    )


def _after_verdict(verdict: dict | None, line: str) -> str:
    words = "Stored answers stay as stored after the verdict."
    change = resolve_change(line)
    if change and change["field"] == "monthly_volume":
        words += " The stated volume is not lowered. ONB-POL-002."
    assignee = ASSIGNEE_WORDS.get(str((verdict or {}).get("assignee") or ""))
    if assignee:
        words += f" The review stays with the {assignee}."
    return words


def which_reply(slots: list[str]) -> str:
    from copilot.say.questions import slot_list

    return f"Which document is this: {slot_list(slots)}? Say its name with the file, such as bank proof bank.pdf."

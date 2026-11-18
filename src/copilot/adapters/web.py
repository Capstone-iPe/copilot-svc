"""Web chat shape. Matches what the web agent reply already carries.

Not a frozen product contract. Change this file when the web app fields change.
"""

from __future__ import annotations

from copilot.adapters.base import Adapter
from copilot.reply import Reply
from copilot.say.questions import answers, prompt_for, slot_list
from copilot.say.redact import redact
from copilot.words import ASSIGNEE_WORDS


class WebAdapter(Adapter):
    def open(self, step: dict) -> dict:
        prompt = prompt_for(step)
        return {
            "text": prompt,
            "prompt": prompt,
            "messages": [prompt] if prompt else [],
            "asking": _asking(step),
            "card": None,
            "application_id": step.get("application_id"),
        }

    def render(self, reply: Reply, *, line: str = "") -> dict:
        text = redact(reply.text, line) if reply.text else ""
        prompt = reply.prompt or ""
        messages = []
        if text.strip():
            messages.append(text.strip())
        if prompt.strip() and prompt.strip() not in messages:
            messages.append(prompt.strip())
        shown = " ".join(messages)
        return {
            "text": shown,
            "prompt": prompt,
            "messages": messages,
            "asking": _asking(reply.step),
            "card": _card(reply.step),
            "application_id": reply.step.get("application_id"),
        }


def _asking(step: dict) -> str | None:
    pending = step.get("pending") if isinstance(step.get("pending"), dict) else None
    if pending and pending.get("name"):
        return str(pending["name"])
    snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
    if isinstance(snapshot.get("verdict"), dict):
        return None
    return "submit"


def _card(step: dict) -> dict | None:
    snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
    verdict = snapshot.get("verdict")
    if not isinstance(verdict, dict):
        return None
    outcome = str(verdict.get("outcome") or "")
    review_id = verdict.get("review_id")
    assignee = ASSIGNEE_WORDS.get(str(verdict.get("assignee") or ""))
    missing = [str(item) for item in verdict.get("missing_items") or []]
    shop = str(answers(snapshot).get("shop_name") or "")
    return {
        "type": "verdict",
        "outcome": outcome,
        "review_id": review_id,
        "assignee": assignee,
        "missing": slot_list(missing) if missing else "",
        "shop_name": shop,
        "citations": [str(item) for item in verdict.get("citations") or []],
    }

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
        return {
            "text": prompt_for(step),
            "prompt": prompt_for(step),
            "asking": _asking(step),
            "card": None,
            "application_id": step.get("application_id"),
        }

    def render(self, reply: Reply, *, line: str = "") -> dict:
        text = redact(reply.text, line) if reply.text else ""
        prompt = reply.prompt or ""
        shown = f"{text} {prompt}".strip() if text and prompt and prompt not in text else (text or prompt)
        return {
            "text": shown,
            "prompt": prompt,
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

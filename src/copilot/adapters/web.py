"""Web ConversationView shape (copilot-web-app contracts).

Pills stay minimal: upload / submit only. No suggestion chips.
"""

from __future__ import annotations

import time
import uuid

from copilot.adapters.base import Adapter
from copilot.reply import Reply
from copilot.say.greeting import welcome_text
from copilot.say.questions import answers, prompt_for
from copilot.say.redact import redact

UPLOADS = {
    "business_registration",
    "owner_id",
    "bank_proof",
    "shopfront_photo",
    "dpa_addendum",
}
ACCEPT = [".pdf", ".jpg", ".jpeg", ".png"]
ITEM = {
    "business_registration": "business registration",
    "owner_id": "owner's government ID",
    "bank_proof": "bank proof",
    "shopfront_photo": "shopfront photo",
    "dpa_addendum": "data-processing addendum",
}


class WebAdapter(Adapter):
    def open(self, step: dict, *, merchant_name: str | None = None) -> dict:
        """Welcome, then the first question — two assistant messages, same as CLI."""
        asking = asking_for(step)
        welcome = welcome_text(merchant_name)
        question = (prompt_for(step) or "").strip()
        now = _now()
        messages = [_message("assistant", welcome, now)]
        if question:
            messages.append(_message("assistant", question, now))
        return {
            "asking": asking,
            "messages": messages,
            "prompt": prompt_view(asking),
            "shop_name": None,
            "status": "DRAFT",
            "review_id": None,
            "result": None,
            "steps": steps_for(asking, "DRAFT"),
        }

    def render(self, reply: Reply, *, line: str = "") -> dict:
        """Assistant lines for one turn. App appends them to ConversationView."""
        text = redact(reply.text, line) if reply.text else ""
        next_prompt = reply.prompt or ""
        parts = []
        if text.strip():
            parts.append(text.strip())
        if next_prompt.strip() and next_prompt.strip() not in parts:
            parts.append(next_prompt.strip())
        asking = asking_for(reply.step)
        result = result_for(reply.step)
        status = result["outcome"] if result else "DRAFT"
        snapshot = reply.step.get("snapshot") if isinstance(reply.step.get("snapshot"), dict) else {}
        shop = answers(snapshot).get("shop_name")
        return {
            "asking": asking,
            "assistant_texts": parts,
            "prompt": prompt_view(asking),
            "shop_name": str(shop) if shop else None,
            "status": status,
            "review_id": (result or {}).get("review_id"),
            "result": result,
            "steps": steps_for(asking, status),
            "card": _result_card(result) if result else None,
        }


def asking_for(step: dict) -> str | None:
    pending = step.get("pending") if isinstance(step.get("pending"), dict) else None
    if pending and pending.get("name"):
        return str(pending["name"])
    snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
    if isinstance(snapshot.get("verdict"), dict):
        return None
    return "submit"


def prompt_view(asking: str | None) -> dict:
    if asking in UPLOADS:
        return {
            "field": asking,
            "kind": "upload",
            "input": True,
            "accept": ACCEPT,
            "pills": [
                {
                    "label": f"Upload {ITEM.get(asking, asking)}",
                    "action": "upload",
                    "document": asking,
                }
            ],
        }
    if asking == "submit":
        return {
            "field": "summary",
            "kind": "summary",
            "input": True,
            "accept": [],
            "pills": [{"label": "Submit", "action": "submit"}],
        }
    if asking is None:
        return {"field": None, "kind": "closed", "input": True, "pills": [], "accept": ACCEPT}
    return {"field": asking, "kind": "text", "input": True, "pills": [], "accept": []}


def steps_for(asking: str | None, status: str) -> dict:
    if status and status != "DRAFT":
        return {"shop_details": "done", "documents": "done", "submitted": "done"}
    if asking in UPLOADS:
        return {"shop_details": "done", "documents": "current", "submitted": "todo"}
    if asking == "submit":
        return {"shop_details": "done", "documents": "done", "submitted": "current"}
    return {"shop_details": "current", "documents": "todo", "submitted": "todo"}


def result_for(step: dict) -> dict | None:
    snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
    verdict = snapshot.get("verdict")
    if not isinstance(verdict, dict):
        return None
    missing = [str(item) for item in verdict.get("missing_items") or []]
    volume = verdict.get("volume_inr")
    try:
        volume_inr = int(volume) if volume is not None else 0
    except (TypeError, ValueError):
        volume_inr = 0
    return {
        "outcome": str(verdict.get("outcome") or ""),
        "missing_items": missing,
        "assignee": verdict.get("assignee"),
        "review_id": verdict.get("review_id"),
        "citations": [str(item) for item in verdict.get("citations") or []],
        "volume_inr": volume_inr,
    }


def _result_card(result: dict) -> dict:
    return {"type": "result", **result}


def _message(role: str, text: str, created_at: str, *, attachments=None, card=None) -> dict:
    return {
        "id": "m_" + uuid.uuid4().hex[:12],
        "role": role,
        "text": text or "",
        "attachments": attachments or [],
        "card": card,
        "created_at": created_at,
    }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_message(role: str, text: str, *, attachments=None, card=None) -> dict:
    return _message(role, text, _now(), attachments=attachments, card=card)


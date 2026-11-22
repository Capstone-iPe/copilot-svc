"""Web ConversationView shape (copilot-web-app contracts).

Pills stay minimal: upload / submit only. No suggestion chips.
"""

from __future__ import annotations

import time
import uuid

from copilot.adapters.base import Adapter
from copilot.reply import Reply
from copilot.say.greeting import welcome_back, welcome_text
from copilot.say.questions import UPLOADS as UPLOAD_TEXT
from copilot.say.questions import WEB_UPLOADS, answers, prompt_for
from copilot.say.redact import redact

UPLOADS = {
    "business_registration",
    "owner_id",
    "bank_proof",
    "shopfront_photo",
    "dpa_addendum",
}
ACCEPT = [".pdf", ".jpg", ".jpeg", ".png"]
_DOCS = "All the questions are done. Just the documents left. "
ITEM = {
    "business_registration": "business registration",
    "owner_id": "owner's government ID",
    "bank_proof": "bank proof",
    "shopfront_photo": "shopfront photo",
    "dpa_addendum": "data-processing addendum",
}


class WebAdapter(Adapter):
    def open(self, step: dict, *, merchant_name: str | None = None, returning: bool = False) -> dict:
        """Welcome, then the first question — two assistant messages, same as CLI."""
        asking = asking_for(step)
        snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
        welcome = welcome_back(merchant_name, snapshot) if returning else welcome_text(merchant_name)
        question = (prompt_for(step, web=True) or "").strip()
        now = _now()
        messages = [_message("assistant", welcome, now)]
        if question:
            messages.append(_message("assistant", question, now))
        shop = answers(snapshot).get("shop_name")
        return {
            "asking": asking,
            "messages": messages,
            "prompt": prompt_view(asking, snapshot=snapshot),
            "shop_name": str(shop) if shop else None,
            "status": "DRAFT",
            "review_id": None,
            "result": None,
            "steps": steps_for(asking, "DRAFT"),
        }

    def render(self, reply: Reply, *, line: str = "") -> dict:
        """Assistant lines for one turn. App appends them to ConversationView."""
        text = redact(reply.text, line) if reply.text else ""
        next_prompt = reply.prompt or ""
        lead = ""
        if next_prompt.startswith(_DOCS):
            lead = _DOCS
            next_prompt = next_prompt[len(_DOCS) :]
        asking_now = asking_for(reply.step)
        if asking_now in UPLOAD_TEXT and next_prompt.strip() == UPLOAD_TEXT[asking_now]:
            next_prompt = WEB_UPLOADS.get(asking_now, next_prompt)
        if lead:
            next_prompt = lead + next_prompt
        parts = []
        if text.strip():
            parts.append(text.strip())
        if next_prompt.strip() and next_prompt.strip() not in parts:
            parts.append(next_prompt.strip())
        asking = reply.trace.get("asking") or asking_for(reply.step)
        result = result_for(reply.step)
        status = result["outcome"] if result else "DRAFT"
        snapshot = reply.step.get("snapshot") if isinstance(reply.step.get("snapshot"), dict) else {}
        shop = answers(snapshot).get("shop_name")
        return {
            "asking": asking,
            "assistant_texts": parts,
            "prompt": prompt_view(asking, snapshot=snapshot),
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


_CHOICES = {
    "business_type": ["Restaurant", "Grocery", "Retail"],
    "payment_methods": ["UPI", "Cards", "UPI and cards"],
    "stores_payer_phones": ["Yes", "No"],
    "note": ["No note"],
}

_EDITABLE_FIELDS = [
    ("Shop name", "Change shop name"),
    ("City", "Change city"),
    ("Business type", "Change business type"),
    ("Monthly volume", "Change monthly volume"),
    ("Payment methods", "Change payment methods"),
    ("Payer phones", "Change payer phones"),
    ("Business registration", "Change business registration"),
    ("Owner's government ID", "Change owner's government id"),
    ("Bank proof", "Change bank proof"),
    ("Shopfront photo", "Change shopfront photo"),
    ("Note", "Change note"),
]

WHY_PILL = {"label": "Why is this needed?", "action": "send", "value": "Why is this needed?"}


def prompt_view(asking: str | None, snapshot: dict | None = None) -> dict:
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
                },
                {"label": "I don't have this", "action": "send", "value": "I don't have this file."},
                WHY_PILL,
            ],
        }
    if asking == "submit":
        return {
            "field": "summary",
            "kind": "summary",
            "input": True,
            "accept": [],
            "pills": [
                {"label": "Submit", "action": "submit"},
                {"label": "Change an answer", "action": "send", "value": "Change an answer"},
            ],
        }
    if asking == "change":
        pills = [{"label": label, "action": "send", "value": val} for label, val in _EDITABLE_FIELDS]
        return {"field": "change", "kind": "choice", "input": True, "pills": pills, "accept": []}
    if asking is None:
        pills = []
        if snapshot:
            files = snapshot.get("files") or {}
            verdict = snapshot.get("verdict") or {}
            missing_items = list(verdict.get("missing_items") or [])
            for slot, facts in files.items():
                if isinstance(facts, dict) and facts.get("state") in {"missing", "rejected"} and slot in UPLOADS:
                    if slot not in missing_items:
                        missing_items.append(slot)
            for slot in missing_items:
                if slot in UPLOADS:
                    pills.append({
                        "label": f"Upload {ITEM.get(slot, slot)}",
                        "action": "upload",
                        "document": slot,
                    })
        return {"field": None, "kind": "closed", "input": True, "pills": pills, "accept": ACCEPT}
    if asking in _CHOICES:
        pills = [{"label": c, "action": "send", "value": c} for c in _CHOICES[asking]]
        pills.append(WHY_PILL)
        return {"field": asking, "kind": "choice", "input": True, "pills": pills, "accept": []}
    pills = [WHY_PILL] if asking in {"shop_name", "monthly_volume"} else []
    return {"field": asking, "kind": "text", "input": True, "pills": pills, "accept": []}


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


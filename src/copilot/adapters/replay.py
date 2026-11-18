"""Replay shape: the fields the eval checker reads."""

from __future__ import annotations

from copilot.adapters.base import Adapter
from copilot.reply import Reply
from copilot.say.questions import prompt_for


class ReplayAdapter(Adapter):
    def open(self, step: dict) -> dict:
        prompt = prompt_for(step)
        return {
            "text": "",
            "prompt": prompt,
            "messages": [prompt] if prompt else [],
            "action": "",
            "pending_name": _pending_name(step),
            "outcome": _outcome(step),
            "review_id": _review_id(step),
        }

    def render(self, reply: Reply, *, line: str = "") -> dict:
        text = reply.text or ""
        prompt = reply.prompt or ""
        messages = list(reply.messages) if reply.messages else (
            ([text] if text else []) + ([prompt] if prompt and prompt != text else [])
        )
        return {
            "text": text,
            "prompt": prompt,
            "messages": messages,
            "action": str(reply.trace.get("action") or ""),
            "pending_name": _pending_name(reply.step),
            "outcome": _outcome(reply.step),
            "review_id": _review_id(reply.step),
        }


def _pending_name(step: dict) -> str | None:
    pending = step.get("pending") if isinstance(step.get("pending"), dict) else None
    if not pending:
        return None
    name = pending.get("name")
    return str(name) if name else None


def _snapshot(step: dict) -> dict:
    found = step.get("snapshot")
    return found if isinstance(found, dict) else {}


def _verdict(step: dict) -> dict:
    found = _snapshot(step).get("verdict")
    return found if isinstance(found, dict) else {}


def _outcome(step: dict) -> str | None:
    value = _verdict(step).get("outcome")
    return str(value) if value else None


def _review_id(step: dict) -> str | None:
    value = _verdict(step).get("review_id")
    return str(value) if value else None

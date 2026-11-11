"""Terminal shape: text and the next prompt."""

from __future__ import annotations

from copilot.adapters.base import Adapter
from copilot.reply import Reply
from copilot.say.questions import prompt_for
from copilot.say.redact import redact


class CliAdapter(Adapter):
    def open(self, step: dict) -> dict:
        return {"text": "", "prompt": prompt_for(step)}

    def render(self, reply: Reply, *, line: str = "") -> dict:
        return {
            "text": redact(reply.text, line) if reply.text else "",
            "prompt": reply.prompt or "",
        }

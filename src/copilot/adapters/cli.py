"""Terminal shape: text and the next prompt."""

from __future__ import annotations

from copilot.adapters.base import Adapter
from copilot.reply import Reply
from copilot.say.questions import prompt_for
from copilot.say.redact import redact


class CliAdapter(Adapter):
    def open(self, step: dict) -> dict:
        prompt = prompt_for(step)
        return {"text": "", "prompt": prompt, "messages": [prompt] if prompt else []}

    def render(self, reply: Reply, *, line: str = "") -> dict:
        text = redact(reply.text, line) if reply.text else ""
        prompt = reply.prompt or ""
        messages = []
        if text.strip():
            messages.append(text.strip())
        if prompt.strip() and prompt.strip() not in messages:
            messages.append(prompt.strip())
        return {"text": text, "prompt": prompt, "messages": messages}

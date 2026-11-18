"""What one turn gives back. Adapters shape it for CLI / web / replay."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Reply:
    text: str
    prompt: str
    trace: dict
    step: dict
    messages: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.messages:
            return
        parts: list[str] = []
        if self.text.strip():
            parts.append(self.text.strip())
        if self.prompt.strip() and self.prompt.strip() not in parts:
            parts.append(self.prompt.strip())
        self.messages = parts

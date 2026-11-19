"""Where the chat is, apart from the answers ONB stores."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DialogueState:
    focus: str | None = None
    awaiting: str | None = None
    last_saved: str | None = None
    recent: list[tuple[str, str]] = field(default_factory=list)

    def note(self, role: str, text: str) -> None:
        if text.strip():
            self.recent.append((role, text.strip()))
            self.recent = self.recent[-6:]

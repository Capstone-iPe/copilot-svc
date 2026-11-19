"""Where the chat is, apart from the answers ONB stores."""

from __future__ import annotations

from dataclasses import dataclass, field

from copilot.words import DIGITS


@dataclass
class DialogueState:
    focus: str | None = None
    resume_to: str | None = None
    awaiting: str | None = None
    proposed: dict | None = None
    last_saved: str | None = None
    recent: list[tuple[str, str]] = field(default_factory=list)

    def note(self, role: str, text: str) -> None:
        clean = DIGITS.sub("[number hidden]", text.strip())
        if clean:
            self.recent.append((role, clean))
            self.recent = self.recent[-6:]

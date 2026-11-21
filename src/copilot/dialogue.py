"""Where the chat is, apart from the answers ONB stores."""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from copilot.words import DIGITS


@dataclass
class DialogueState:
    focus: str | None = None
    awaiting: str | None = None
    proposed: dict | None = None
    last_saved: str | None = None
    misses: int = 0
    miss_field: str | None = None
    values: dict[str, list[str]] = field(default_factory=dict)
    recent: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def restore(cls, saved: dict) -> DialogueState:
        known = {item.name for item in fields(cls)}
        state = cls(**{key: value for key, value in saved.items() if key in known})
        state.recent = [(role, text) for role, text in state.recent]
        return state

    def remember(self, name: str, value: str) -> None:
        if name == "note":
            return
        prior = self.values.setdefault(name, [])
        if value and (not prior or prior[-1] != value):
            prior.append(value)

    def note(self, role: str, text: str) -> None:
        clean = DIGITS.sub("[number hidden]", text.strip())
        if clean:
            self.recent.append((role, clean))
            self.recent = self.recent[-6:]

"""One rule for every consumer: open the step, then render each Reply."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from copilot.reply import Reply


@runtime_checkable
class Adapter(Protocol):
    def open(self, step: dict) -> dict:
        """The first screen, before any merchant line."""

    def render(self, reply: Reply, *, line: str = "") -> dict:
        """One turn's Reply as this consumer expects it."""

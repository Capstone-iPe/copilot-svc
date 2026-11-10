"""The hosted chat call. Tests use RecordedChat instead."""

from __future__ import annotations

from typing import Protocol


class ChatModel(Protocol):
    def complete(self, messages: list[dict], max_tokens: int, schema: dict | None = None) -> str | None:
        """One completion. None when the endpoint is unset or the call fails."""

"""Replays saved replies. A prompt change misses the hash and returns None."""

from __future__ import annotations

import hashlib
import json


class RecordedChat:
    def __init__(self, store: dict[str, str] | None = None) -> None:
        self.store = store or {}
        self.misses: list[str] = []

    def complete(self, messages: list[dict], max_tokens: int, schema: dict | None = None) -> str | None:
        key = _key(messages, max_tokens, schema)
        if key not in self.store:
            self.misses.append(key)
            return None
        return self.store[key]


def _key(messages: list[dict], max_tokens: int, schema: dict | None) -> str:
    payload = {"messages": messages, "max_tokens": max_tokens, "schema": schema}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()

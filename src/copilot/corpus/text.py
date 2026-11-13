"""Light text helpers the why-path still needs locally."""

from __future__ import annotations

import re

TOKEN = re.compile(r"[a-z0-9§]+(?:-[a-z0-9§]+)*")


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def search_text(row: dict) -> str:
    return row.get("search_text") or row["text"]

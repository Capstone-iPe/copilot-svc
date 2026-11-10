"""The held line, spoken to the merchant."""

from __future__ import annotations

import re

from copilot.words import HELD, MEMO_VOICE


def _merchant_held(held: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", held.strip())
    kept = [sentence for sentence in sentences if sentence and not MEMO_VOICE.search(sentence)]
    return " ".join(kept)


def passage_fallback(passages: list[dict]) -> str:
    for row in passages:
        held = HELD.search(row["text"])
        if not held:
            continue
        words = _merchant_held(held.group(1))
        if words:
            return f"{words} {row['document_id']}."
    if passages:
        return f"The onboarding policies do not state that. {passages[0]['document_id']}."
    return "The onboarding policies do not state that."

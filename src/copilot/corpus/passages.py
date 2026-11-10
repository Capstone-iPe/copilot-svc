"""Search results the why path reads. Corpus is the implementation."""

from __future__ import annotations

from typing import Protocol


class Passages(Protocol):
    rows: list[dict]
    document_ids: set[str]

    def search(self, query: str, k: int = 4) -> list[dict]:
        """In-force chunks, one per document."""

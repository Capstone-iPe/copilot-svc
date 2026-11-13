"""Choose which passages the model sees."""

from __future__ import annotations

from copilot.corpus.text import search_text, tokens
from copilot.words import DOC_ID, FIELD_WHY_FOLDERS, WHY_STOP


def prefer_held(hits: list[dict], rows: list[dict]) -> list[dict]:
    """Use the chunk that carries the held line when the same document has one."""
    held: dict[str, dict] = {}
    for row in rows:
        document_id = str(row.get("document_id") or "")
        if document_id and document_id not in held and "## Held" in str(row.get("text") or ""):
            held[document_id] = row
    return [held.get(str(row.get("document_id") or ""), row) for row in hits]


def named_words(line: str, topic: str, candidates: list[dict]) -> set[str]:
    """Words the merchant used that a substitute memo also uses."""
    skip = WHY_STOP | set(tokens(topic))
    words = {word for word in tokens(line) if word not in skip and len(word) > 2}
    found: set[str] = set()
    for row in candidates:
        if (row.get("folder") or "") in FIELD_WHY_FOLDERS:
            continue
        found |= words & set(tokens(search_text(row)))
    return found


def passages_for_why(line: str, topic: str, field_hits: list[dict], named_hits: list[dict]) -> list[dict]:
    """The field's own why, plus a substitute memo only when the merchant names it."""
    named = named_words(line, topic, [*field_hits, *named_hits])
    kept: list[dict] = []
    seen: set[str] = set()

    def add(row: dict) -> None:
        document_id = str(row.get("document_id") or "")
        if not document_id or document_id in seen or len(kept) == 3:
            return
        seen.add(document_id)
        kept.append(row)

    for row in field_hits:
        if sum((item.get("folder") or "") in FIELD_WHY_FOLDERS for item in kept) == 2:
            break
        if (row.get("folder") or "") in FIELD_WHY_FOLDERS:
            add(row)
    if named:
        for row in [*field_hits, *named_hits]:
            if named_words(line, topic, [row]):
                add(row)
    return kept


def allowed_ids(passages: list[dict], facts: dict | None, in_force: set[str]) -> set[str]:
    """Ids the passages or the verdict name, kept only when the corpus holds them in force."""
    named = {row["document_id"] for row in passages}
    for row in passages:
        named |= set(DOC_ID.findall(row["text"]))
    named |= {found for item in (facts or {}).get("citations") or [] for found in DOC_ID.findall(str(item))}
    return named & in_force

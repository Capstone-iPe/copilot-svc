"""Drop an explanation that claims too much or repeats its instructions."""

from __future__ import annotations

import re

from copilot.words import DIGITS, DOC_ID, LIVE_CLAIM, MAX_EXPLANATION, MEMO_VOICE, REVIEW_ID, SECTION


def cited_sections(text: str) -> set[str]:
    return {f"{doc} §{number}" for doc, number in SECTION.findall(text)}


def critic(text: str, allowed_ids: set[str], known: str) -> bool:
    if not text or len(text) > MAX_EXPLANATION:
        return False
    if MEMO_VOICE.search(text) or LIVE_CLAIM.search(text):
        return False
    if any(found not in known for found in REVIEW_ID.findall(text)):
        return False
    if _bad_document(text, allowed_ids):
        return False
    shown = cited_sections(known)
    if any(cite not in shown for cite in cited_sections(text)):
        return False
    return _digits_known(text, known)


def _bad_document(text: str, allowed_ids: set[str]) -> bool:
    for found in DOC_ID.findall(text):
        if found.startswith("ONB-DRAFT") or found not in allowed_ids:
            return True
    return False


def _digits_known(text: str, known: str) -> bool:
    known_digits = re.sub(r"\D", "", known)
    for found in DIGITS.findall(text):
        if re.sub(r"\D", "", found) not in known_digits:
            return False
    return True


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def _key(sentence: str) -> str:
    return re.sub(r"\s+", " ", sentence).lower().strip(" .!?")


def without_prompt(reply: str, prompt: str) -> str:
    """Drop a sentence the model copied from its instructions."""
    banned = {_key(sentence) for sentence in _sentences(prompt)}
    banned.discard("")
    kept = []
    for sentence in _sentences(reply):
        key = _key(sentence)
        if not key or key in banned or any(len(phrase) > 15 and phrase in key for phrase in banned):
            continue
        kept.append(sentence)
    return " ".join(kept)

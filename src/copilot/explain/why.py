"""Plain field why, and a free question (ask) that needs more than the field topic."""

from __future__ import annotations

import json

from copilot.explain.checker import critic, without_prompt
from copilot.explain.fallback import passage_fallback
from copilot.explain.passages import allowed_ids, prefer_held
from copilot.prompts import explain_prompt
from copilot.words import DOC_ID, FIELD_TOPICS, SLOT_WORDS

_PLAIN = (
    "Answer why this field is being asked, in at most two short sentences. "
    "Phrase the passage that says why. Do not mention a document the merchant did not name."
)
_FREE = (
    "Answer only the merchant's question from the passages, in one or two short sentences. "
    "If the passages do not define what they asked, say the onboarding policies do not state it. "
    "Do not say why the current field is being asked. Do not invent a definition."
)


def why_question(line: str, topic: str, mode: str, named: set[str]) -> str:
    if mode == "free" or named:
        return line
    return f"Why {topic}?" if topic else line


def why_instruction(mode: str) -> str:
    return _FREE if mode == "free" else _PLAIN


def explain(question, passages, instruction, in_force, complete, facts=None):
    """One model sentence from the passages, or None when it fails the check."""
    if not passages:
        return None
    quoted = "\n\n".join(row.get("search_text") or row["text"] for row in passages[:3])
    prompt = explain_prompt(instruction)
    reply = complete(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps({"question": question, "passages": quoted}, ensure_ascii=False)},
        ],
        120,
        None,
    )
    return _checked(reply, prompt, quoted, passages, facts, in_force)


def _checked(reply, prompt, quoted, passages, facts, in_force):
    if not reply:
        return None
    reply = without_prompt(" ".join(reply.split()), prompt)
    if not reply:
        return None
    known = quoted + json.dumps(facts or {})
    return reply if critic(reply, allowed_ids(passages, facts, in_force), known) else None


def why_reply(line, pending, corpus, complete, mode: str = "plain") -> tuple[str, str]:
    name = str(pending.get("name") or "") if pending else ""
    topic = FIELD_TOPICS.get(name) or SLOT_WORDS.get(name, "")
    query = f"why {topic}".strip() if topic else line
    field_hits = prefer_held(corpus.search(query, k=8), corpus.rows)
    field_passages = _field_passages(field_hits)
    if mode != "free":
        return _from_passages(why_question(line, topic, mode, set()), field_passages, _PLAIN, corpus, complete)
    return _ask_reply(line, field_passages, corpus, complete)


def _ask_reply(line, field_passages, corpus, complete) -> tuple[str, str]:
    """The merchant's question, then the pending field's own reason."""
    side_hits = prefer_held(corpus.search(line, k=8), corpus.rows)
    side = _other_passages(side_hits, field_passages)
    answer = explain(line, side, _FREE, corpus.document_ids, complete) if side else None
    if answer and side and not DOC_ID.search(answer):
        answer += f" {side[0]['document_id']}."
    if not answer:
        answer = "The onboarding policies do not state that."
        if side:
            answer += f" {side[0]['document_id']}."
    field = passage_fallback(field_passages)
    if field and field not in answer:
        answer = f"{answer} {field}"
    return answer.strip(), "model"


def _from_passages(question, passages, instruction, corpus, complete) -> tuple[str, str]:
    answer = explain(question, passages, instruction, corpus.document_ids, complete)
    if answer:
        if passages and not DOC_ID.search(answer):
            answer += f" {passages[0]['document_id']}."
        return answer, "model"
    return passage_fallback(passages), "fallback"


def _other_passages(hits: list[dict], field_passages: list[dict]) -> list[dict]:
    skip = {str(row.get("document_id") or "") for row in field_passages}
    kept: list[dict] = []
    seen: set[str] = set()
    for row in hits:
        document_id = str(row.get("document_id") or "")
        if not document_id or document_id in skip or document_id in seen or len(kept) == 3:
            continue
        seen.add(document_id)
        kept.append(row)
    return kept


def _field_passages(field_hits: list[dict]) -> list[dict]:
    """Plain why uses only the field's own faq/policy hits."""
    from copilot.words import FIELD_WHY_FOLDERS

    kept: list[dict] = []
    seen: set[str] = set()
    for row in field_hits:
        document_id = str(row.get("document_id") or "")
        if not document_id or document_id in seen or len(kept) == 3:
            continue
        if (row.get("folder") or "") not in FIELD_WHY_FOLDERS:
            continue
        seen.add(document_id)
        kept.append(row)
    return kept


def verdict_explanation(verdict: dict, corpus, complete) -> str | None:
    from copilot.say.questions import slot_list

    missing = slot_list([str(item) for item in verdict.get("missing_items") or []])
    citations = " ".join(str(item) for item in verdict.get("citations") or [])
    query = f"why {missing} {citations}".strip()
    if query == "why":
        return None
    return explain(
        query,
        corpus.search(query, k=3),
        "Write one short sentence that explains the rule behind this result. Do not restate the "
        "outcome, the reviewer, or the review id.",
        corpus.document_ids,
        complete,
        facts=verdict,
    )

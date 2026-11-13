"""Plain why, and a question that asks for more than why."""

from __future__ import annotations

import json

from copilot.explain.checker import critic, without_prompt
from copilot.explain.fallback import passage_fallback
from copilot.explain.passages import allowed_ids, named_words, passages_for_why, prefer_held
from copilot.prompts import explain_prompt
from copilot.words import DOC_ID, FIELD_TOPICS, SLOT_WORDS, WHY_STOP


def asks_more_than_why(line: str) -> bool:
    """True when the merchant asked something besides why this field is on screen."""
    from copilot.corpus.text import tokens

    plain = WHY_STOP | {"but", "about", "just", "then", "also", "still"}
    return any(len(word) > 2 and word not in plain for word in tokens(line))


def why_question(line: str, topic: str, named: set[str]) -> str:
    if named or asks_more_than_why(line):
        return line
    return f"Why {topic}?" if topic else line


def why_instruction(line: str) -> str:
    if asks_more_than_why(line):
        return (
            "Answer the merchant's question from the passages. If the passages do not define "
            "the word they asked about, say the onboarding policies do not state it. Then say "
            "why this field is being asked, from the passage that says why. Do not invent a "
            "definition. Do not mention a document the merchant did not name."
        )
    return (
        "Answer why this field is being asked, in at most two short sentences. "
        "Phrase the passage that says why. Do not mention a document the merchant did not name."
    )


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


def why_reply(line, pending, corpus, complete) -> tuple[str, str]:
    name = str(pending.get("name") or "") if pending else ""
    topic = FIELD_TOPICS.get(name) or SLOT_WORDS.get(name, "")
    query = f"why {topic}".strip() if topic else line
    field_hits = prefer_held(corpus.search(query, k=8), corpus.rows)
    named = named_words(line, topic, field_hits)
    named_hits = corpus.search(line, k=4) if named else []
    passages = passages_for_why(line, topic, field_hits, named_hits)
    answer = explain(why_question(line, topic, named), passages, why_instruction(line), corpus.document_ids, complete)
    if answer:
        if not DOC_ID.search(answer):
            answer += f" {passages[0]['document_id']}."
        return answer, "model"
    return passage_fallback(passages), "fallback"


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

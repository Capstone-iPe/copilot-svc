"""Play replay/natural through Session. One row is one turn, seeded to its stored answers.

Needs CHAT_API_KEY. Why and ask rows also need CORPUS_SEARCH_URL and CORPUS_API_KEY.
Pass --holdout to play holdout.jsonl once. Pass --limit to try a few rows first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv

load_dotenv(HERE.parent / ".env")

from copilot.chat.qwen_chat import QwenChat
from copilot.corpus.remote import RemoteCorpus
from copilot.say.questions import answers
from copilot.session import Session
from memory_onb import MemoryOnb

_SAVE_ACTS = {"answer", "correct", "confirm_yes"}
_QUIET = {"chitchat", "pause"}


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _same(got: str, wanted: str) -> bool:
    return " ".join(str(got).split()).casefold() == " ".join(str(wanted).split()).casefold()


async def seed(session: Session, onb: MemoryOnb, row: dict) -> str | None:
    stored = row.get("stored") if isinstance(row.get("stored"), dict) else {}
    target = row.get("pending")
    for _ in range(16):
        pending = session.step.get("pending") if isinstance(session.step.get("pending"), dict) else None
        name = pending.get("name") if pending else None
        if name == target:
            return None
        if not pending:
            return f"pending ended at {name}, wanted {target}"
        if pending.get("kind") == "field" and name in stored:
            await onb.save_answer(session.application_id, name, str(stored[name]))
        elif pending.get("kind") == "upload":
            await onb.save_file(session.application_id, name, file=f"{name}.pdf")
        else:
            return f"pending={name}, wanted {target}"
        session.step = await onb.next_step(session.application_id)
    return "could not reach the labeled question"


def _prepare(session: Session, row: dict) -> None:
    for act in row.get("acts") or []:
        if act.get("type") not in {"confirm_yes", "confirm_no"}:
            continue
        field = str(act.get("field") or "")
        session.dialogue.awaiting = f"confirm:{field}"
        session.dialogue.proposed = {"field": field, "value": str(act.get("value_span") or "")}
        return


def _score(row: dict, before: dict, after: dict, action: str, pending_after) -> dict:
    fresh = {key: value for key, value in after.items() if before.get(key) != value}
    expected = {item["field"]: str(item["value"]) for item in row.get("saves") or []}
    blocked = set(row.get("does_not_save") or [])
    kinds = {str(act.get("type") or "") for act in row.get("acts") or []}
    wrong = [key for key in fresh if key in blocked or key not in expected]
    wrong += [key for key in expected if key not in fresh]
    small = bool(fresh) and row.get("category") in _QUIET
    field_ok = all(key in fresh for key in expected) if expected else not fresh
    value_ok = all(key in fresh and _same(fresh[key], value) for key, value in expected.items()) if expected else not fresh
    if expected:
        act_ok = bool(kinds & _SAVE_ACTS) and not wrong
    else:
        act_ok = action in kinds or (action == "save" and bool(kinds & _SAVE_ACTS))
    back = True
    if not (kinds & _SAVE_ACTS):
        name = pending_after.get("name") if isinstance(pending_after, dict) else None
        back = name == row.get("pending")
    return {"wrong": wrong, "small": small, "field": field_ok, "value": value_ok, "act": act_ok, "back": back, "fresh": fresh}


async def play(row: dict, corpus, chat) -> tuple[str | None, dict | None]:
    onb = MemoryOnb()
    step = await onb.next_step()
    session = Session(chat, onb, corpus, step["application_id"], step)
    problem = await seed(session, onb, row)
    if problem:
        return problem, None
    _prepare(session, row)
    before = dict(answers(session.step.get("snapshot") or {}))
    reply = await session.turn(str(row.get("said") or ""))
    after = dict(answers(reply.step.get("snapshot") or {}))
    action = str(reply.trace.get("action") or reply.trace.get("intent") or "")
    return None, _score(row, before, after, action, reply.step.get("pending"))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Score replay/natural")
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    path = HERE / "natural" / ("holdout.jsonl" if args.holdout else "turns.jsonl")
    rows = load_rows(path)
    if args.limit:
        rows = rows[: args.limit]
    corpus = RemoteCorpus()
    chat = QwenChat()
    totals = {"rows": 0, "played": 0, "wrong": 0, "small": 0, "field": 0, "value": 0, "act": 0, "back": 0}
    for row in rows:
        totals["rows"] += 1
        problem, score = await play(row, corpus, chat)
        if problem or score is None:
            print(f"FAIL\t{row.get('id')}\t{problem}")
            continue
        totals["played"] += 1
        totals["wrong"] += int(bool(score["wrong"]))
        totals["small"] += int(score["small"])
        totals["field"] += int(score["field"])
        totals["value"] += int(score["value"])
        totals["act"] += int(score["act"])
        totals["back"] += int(score["back"])
        if score["wrong"] or score["small"] or not score["value"]:
            print(f"FAIL\t{row.get('id')}\t{row.get('said')}\twrong={score['wrong']}\tsaved={score['fresh']}")
        else:
            print(f"pass\t{row.get('id')}\t{row.get('said')}")
    played = totals["played"] or 1
    print(
        f"played {totals['played']} of {totals['rows']}"
        f"  wrong-field {totals['wrong']}"
        f"  small-talk-saved {totals['small']}"
        f"  field {totals['field'] / played:.0%}"
        f"  value {totals['value'] / played:.0%}"
        f"  act {totals['act'] / played:.0%}"
        f"  back-on-question {totals['back'] / played:.0%}"
    )


if __name__ == "__main__":
    asyncio.run(main())

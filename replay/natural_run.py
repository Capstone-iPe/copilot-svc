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

from copilot.action.closed import list_value
from copilot.chat.qwen_chat import QwenChat
from copilot.corpus.remote import RemoteCorpus
from copilot.say.questions import answers
from copilot.session import Session
from memory_onb import MemoryOnb

_SAVE_ACTS = {"answer", "correct", "confirm_yes", "upload", "missing"}
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


def _seen(step: dict) -> dict:
    """Stored answers plus a file slot that was accepted or marked missing."""
    snap = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
    found = dict(answers(snap))
    files = snap.get("files") if isinstance(snap.get("files"), dict) else {}
    for slot, file in files.items():
        if isinstance(file, dict) and file.get("state") in {"accepted", "missing"}:
            found[str(slot)] = str(file["state"])
    return found


def _thread_values(row: dict, rows: list[dict]) -> dict[str, list[str]]:
    """Earlier saves in this thread, then the stored snapshot, oldest first."""
    history: dict[str, list[str]] = {}
    for prev in rows:
        if prev.get("thread") != row.get("thread") or str(prev.get("id") or "") >= str(row.get("id") or ""):
            continue
        for item in prev.get("saves") or []:
            field = str(item.get("field") or "")
            value = str(item.get("value") or "").strip()
            if not field or not value:
                continue
            prior = history.setdefault(field, [])
            if not prior or prior[-1] != value:
                prior.append(value)
    for field, value in (row.get("stored") or {}).items():
        text = str(value or "").strip()
        if not text:
            continue
        prior = history.setdefault(str(field), [])
        if not prior or prior[-1] != text:
            prior.append(text)
    return history


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


def _brief(acts) -> list[dict]:
    if not isinstance(acts, list):
        return []
    out = []
    for act in acts:
        if not isinstance(act, dict):
            continue
        out.append({
            "type": act.get("type"),
            "field": act.get("field"),
            "value": act.get("value_span"),
        })
    return out


def _saves(acts: list[dict]) -> dict[str, str]:
    found: dict[str, str] = {}
    for act in acts:
        if act.get("type") in _SAVE_ACTS and act.get("field"):
            found[str(act["field"])] = str(act.get("value") or "")
    return found


class _Watch:
    def __init__(self) -> None:
        self.model: list[dict] = []
        self.checked: list[dict] = []
        self.helpers: list[str] = []

    def reset(self) -> None:
        self.model = []
        self.checked = []
        self.helpers = []


def _install(watch: _Watch) -> None:
    import copilot.action.check as check
    import copilot.session as session

    original = check.check_acts

    def checked(*args, **kwargs):
        watch.model = _brief(args[0] if args else kwargs.get("acts"))
        watch.helpers = []
        result = original(*args, **kwargs)
        watch.checked = _brief(result)
        return result

    check.check_acts = checked
    session.check_acts = checked

    def acts_helper(name, fn):
        def inner(*args, **kwargs):
            before = _brief(args[0]) if args and isinstance(args[0], list) else None
            result = fn(*args, **kwargs)
            after = _brief(result) if isinstance(result, list) else result
            if before is not None and before != after:
                watch.helpers.append(name)
            elif before is None and isinstance(result, dict):
                watch.helpers.append(name)
            return result
        return inner

    for name in ("_confirm_labels", "_prefer_stated", "_pair"):
        setattr(check, name, acts_helper(name, getattr(check, name)))

    closed = check._closed_pending

    def closed_pending(*args, **kwargs):
        field = args[1] if len(args) > 1 else ""
        result = closed(*args, **kwargs)
        if result != field:
            watch.helpers.append("_closed_pending")
        return result

    check._closed_pending = closed_pending

    def field_helper(name, fn):
        def inner(*args, **kwargs):
            result = fn(*args, **kwargs)
            if result:
                watch.helpers.append(name)
            return result
        return inner

    check._fits_pending = field_helper("_fits_pending", check._fits_pending)
    check._awaited_field = field_helper("_awaited_field", check._awaited_field)
    check._recall = acts_helper("_recall", check._recall)


def _cause(row: dict, model: list[dict], checked: list[dict], helpers: list[str], fresh: dict) -> str:
    """Why a played row saved the wrong field. The model acts are the input to check_acts."""
    expected = {item["field"] for item in row.get("saves") or []}
    model_fields = set(_saves(model))
    checked_fields = set(_saves(checked))
    pending = str(row.get("pending") or "")
    said = str(row.get("said") or "")
    if model_fields == expected:
        return "regex" if checked_fields != model_fields else "label"
    fits_pending = bool(pending) and list_value(pending, said) is not None
    retargeted = any(name in helpers for name in ("_closed_pending", "_fits_pending", "_awaited_field"))
    if fits_pending and pending not in model_fields and not retargeted:
        return "missing"
    if set(fresh) == {pending} and expected and pending not in expected and pending.replace("_", " ") not in said.casefold():
        return "label"
    return "model"


async def play(
    row: dict,
    corpus,
    chat,
    watch: _Watch | None = None,
    earlier: list[dict] | None = None,
) -> tuple[str | None, dict | None]:
    onb = MemoryOnb()
    step = await onb.next_step()
    session = Session(chat, onb, corpus, step["application_id"], step)
    problem = await seed(session, onb, row)
    if problem:
        return problem, None
    for field, values in _thread_values(row, earlier or []).items():
        for value in values:
            session.dialogue.remember(field, value)
    _prepare(session, row)
    before = _seen(session.step)
    if watch:
        watch.reset()
    reply = await session.turn(str(row.get("said") or ""))
    after = _seen(reply.step)
    action = str(reply.trace.get("action") or reply.trace.get("intent") or "")
    score = _score(row, before, after, action, reply.step.get("pending"))
    if watch:
        score["model"] = watch.model
        score["checked"] = watch.checked
        score["helpers"] = list(watch.helpers)
        score["cause"] = _cause(row, watch.model, watch.checked, watch.helpers, score["fresh"])
    return None, score


async def main() -> None:
    parser = argparse.ArgumentParser(description="Score replay/natural")
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    path = HERE / "natural" / ("holdout.jsonl" if args.holdout else "turns.jsonl")
    all_rows = load_rows(path)
    rows = all_rows[: args.limit] if args.limit else all_rows
    corpus = RemoteCorpus()
    chat = QwenChat()
    watch = _Watch()
    _install(watch)
    totals = {"rows": 0, "played": 0, "wrong": 0, "small": 0, "field": 0, "value": 0, "act": 0, "back": 0}
    causes: dict[str, int] = {}
    by_category: dict[str, dict[str, int]] = {}
    details = []
    for row in rows:
        totals["rows"] += 1
        problem, score = await play(row, corpus, chat, watch, all_rows)
        if problem or score is None:
            print(f"FAIL\t{row.get('id')}\t{problem}", flush=True)
            continue
        totals["played"] += 1
        totals["wrong"] += int(bool(score["wrong"]))
        totals["small"] += int(score["small"])
        totals["field"] += int(score["field"])
        totals["value"] += int(score["value"])
        totals["act"] += int(score["act"])
        totals["back"] += int(score["back"])
        if score["wrong"]:
            cause = score.get("cause") or "model"
            causes[cause] = causes.get(cause, 0) + 1
            category = str(row.get("category") or "")
            bucket = by_category.setdefault(category, {})
            bucket[cause] = bucket.get(cause, 0) + 1
            details.append({
                "id": row.get("id"),
                "category": category,
                "said": row.get("said"),
                "pending": row.get("pending"),
                "expected": row.get("saves"),
                "saved": score["fresh"],
                "wrong": score["wrong"],
                "model": score.get("model"),
                "checked": score.get("checked"),
                "helpers": score.get("helpers"),
                "cause": cause,
            })
            print(
                f"FAIL\t{row.get('id')}\t{cause}\t{category}\t{row.get('said')}"
                f"\twrong={score['wrong']}\tsaved={score['fresh']}\thelpers={score.get('helpers')}",
                flush=True,
            )
        elif score["small"] or not score["value"]:
            print(f"FAIL\t{row.get('id')}\t{row.get('said')}\twrong={score['wrong']}\tsaved={score['fresh']}", flush=True)
        else:
            print(f"pass\t{row.get('id')}\t{row.get('said')}", flush=True)
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
    if details:
        out = HERE.parent / "docs" / "results" / "natural-wrong-field.jsonl"
        out.write_text("".join(json.dumps(item) + "\n" for item in details), encoding="utf-8")
        print("causes", dict(sorted(causes.items())), flush=True)
        for category, bucket in sorted(by_category.items()):
            print(f"category\t{category}\t{dict(sorted(bucket.items()))}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

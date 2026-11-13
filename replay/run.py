"""Play the eval shops through Session. Outcomes come from eval/README.md.

G-001 to G-050 are the build set. Pass --holdout to run G-051 to G-071 once.
An upload written as "[uploads ...]" becomes "<slot>.pdf". The chat model still
labels every line that is not a fixed command.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
EVAL = HERE.parents[2] / "iPe" / "eval"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from copilot.adapters.replay import ReplayAdapter
from copilot.chat.qwen_chat import QwenChat
from copilot.corpus.remote import RemoteCorpus
from copilot.say.redact import redact
from copilot.session import Session
from copilot.words import LIVE_CLAIM
from memory_onb import MemoryOnb

ADAPTER = ReplayAdapter()

OUTCOME = {
    "In review": "IN_REVIEW",
    "Recommend go-live": "RECOMMEND_GO_LIVE",
    "Refused": "REFUSED",
}
ROW = re.compile(r"\|\s*\[(G-\d+)\][^|]*\|\s*[^|]+\|\s*([^|]+)\|\s*([^|]*)\|")


def expected() -> dict[str, dict]:
    rows = {}
    for case_id, outcome, holdout in ROW.findall((EVAL / "README.md").read_text(encoding="utf-8")):
        rows[case_id] = {"outcome": OUTCOME[outcome.strip()], "holdout": holdout.strip() == "yes"}
    return rows


def merchant_lines(text: str) -> list[str]:
    return [line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("Merchant:")]


def as_said(line: str, pending: dict | None) -> str:
    if line.startswith("[uploads"):
        name = str((pending or {}).get("name") or "file")
        hint = _file_hint(line)
        stem = f"{name}.{hint}" if hint else name
        return f"{stem}.pdf"
    return line


def _file_hint(line: str) -> str:
    """The mock verifier reads dates and the word unsigned from the file text."""
    low = line.lower()
    if "91 days" in low:
        return (date.today() - timedelta(days=91)).isoformat()
    if "90 days" in low:
        return (date.today() - timedelta(days=90)).isoformat()
    if "blank signature" in low or "unsigned" in low:
        return "unsigned"
    return ""


async def play(case_id: str, corpus: Corpus, chat) -> dict:
    onb = MemoryOnb()
    step = await onb.next_step()
    session = Session(chat, onb, corpus, step["application_id"], step)
    problems = []
    review_ids: list[str] = []
    last = ADAPTER.open(step)
    text = (EVAL / "cases" / f"{case_id}.md").read_text(encoding="utf-8")
    for raw in merchant_lines(text):
        pending = session.step.get("pending") if isinstance(session.step.get("pending"), dict) else None
        before = last["pending_name"] or ""
        line = as_said(raw, pending)
        last = ADAPTER.render(await session.turn(line), line=line)
        problems.extend(_turn_problems(last, line, before))
        review_ids.extend(re.findall(r"MR-\d+", last["text"]))
    return _case_result(last, problems, review_ids)


def _turn_problems(out: dict, line: str, before: str) -> list[str]:
    found = []
    if LIVE_CLAIM.search(out["text"]):
        found.append("live claim")
    shown = redact(out["text"], line)
    if "[number hidden]" in shown or _typed_digits(line, shown):
        found.append("typed digits")
    after = out["pending_name"] or ""
    if out["action"] in {"why", "refuse"} and before and after != before:
        found.append(f"left {before}")
    return found


def _typed_digits(line: str, shown: str) -> bool:
    from copilot.words import DIGITS

    for match in DIGITS.findall(line):
        digits = re.sub(r"\D", "", match)
        if digits and digits in re.sub(r"\D", "", shown) and f"MR-{digits}" not in shown:
            return True
    return False


def _case_result(last: dict, problems: list[str], review_ids: list[str]) -> dict:
    review_id = last["review_id"]
    if review_id:
        review_ids.append(str(review_id))
    if len(set(review_ids)) > 1:
        problems.append("review id changed")
    return {"outcome": last["outcome"], "review_id": review_id, "problems": problems}


def judge(case_id: str, result: dict, want: dict) -> list[str]:
    problems = list(result["problems"])
    if result["outcome"] != want["outcome"]:
        problems.append(f"outcome {result['outcome']}")
    if want["outcome"] == "REFUSED" and result["review_id"] is not None:
        problems.append("refused shop has a review id")
    if want["outcome"] != "REFUSED" and not result["review_id"]:
        problems.append("no review id")
    return problems


async def main() -> None:
    parser = argparse.ArgumentParser(description="Replay eval shops through the copilot.")
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    rows = expected()
    chosen = _chosen(rows, args.holdout, args.only)
    corpus = RemoteCorpus()
    chat = QwenChat()
    failed = 0
    for case_id in chosen:
        problems = judge(case_id, await play(case_id, corpus, chat), rows[case_id])
        print(f"{case_id} {'fail ' + '; '.join(problems) if problems else 'pass'}")
        failed += bool(problems)
    print(f"{len(chosen) - failed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)


def _chosen(rows: dict[str, dict], holdout: bool, only: str) -> list[str]:
    if only:
        return [only]
    return [case_id for case_id, row in rows.items() if row["holdout"] is holdout]


if __name__ == "__main__":
    asyncio.run(main())

"""Play replay/questions.txt against MemoryOnb + Session. Needs CHAT_API_KEY."""

from __future__ import annotations

import argparse
import asyncio
import re
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
from copilot.session import Session
from memory_onb import MemoryOnb

FIELDS = [
    "shop_name",
    "city",
    "business_type",
    "monthly_volume",
    "payment_methods",
    "stores_payer_phones",
]
UPLOADS = [
    "business_registration",
    "owner_id",
    "bank_proof",
    "shopfront_photo",
]
SEED = {
    "shop_name": "Replay Tea House",
    "city": "Pune",
    "business_type": "restaurant",
    "monthly_volume": "12 lakh",
    "payment_methods": "UPI and cards",
    "stores_payer_phones": "No",
}


def load_rows() -> list[tuple[str, str, list[str], list[str]]]:
    rows = []
    for raw in (HERE / "questions.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        field, said, must, must_not = line.split("\t")
        rows.append(
            (
                field.strip(),
                said.strip(),
                [p for p in must.split("|") if p],
                [p for p in must_not.split("|") if p],
            )
        )
    return rows


def _match_any(text: str, patterns: list[str]) -> bool:
    low = text.lower()
    return any(p.lower() in low for p in patterns)


async def advance_to(session: Session, onb: MemoryOnb, field: str) -> None:
    aid = session.application_id
    for name in FIELDS:
        pending = session.step.get("pending") or {}
        if pending.get("name") == field:
            return
        if pending.get("kind") == "field" and pending.get("name") in SEED:
            await onb.save_answer(aid, pending["name"], SEED[pending["name"]])
            session.step = await onb.next_step(aid)
    for name in UPLOADS:
        pending = session.step.get("pending") or {}
        if pending.get("name") == field:
            return
        if pending.get("kind") == "upload":
            await onb.save_file(aid, pending["name"], file=f"{pending['name']}.pdf")
            session.step = await onb.next_step(aid)
    if field == "note":
        return


async def play_row(field: str, said: str, must: list[str], must_not: list[str], corpus, chat) -> tuple[str | None, str]:
    onb = MemoryOnb()
    step = await onb.next_step()
    session = Session(chat, onb, corpus, step["application_id"], step)
    await advance_to(session, onb, field)
    pending = session.step.get("pending") or {}
    if pending.get("name") != field:
        return f"pending={pending.get('name')}", ""
    reply = await session.turn(said)
    text = " ".join(reply.messages) if reply.messages else f"{reply.text} {reply.prompt}"
    if must and not _match_any(text, must):
        return f"missing must_contain in: {text[:180]}", text
    if must_not and _match_any(text, must_not):
        return f"hit must_not in: {text[:180]}", text
    return None, text


async def main() -> None:
    parser = argparse.ArgumentParser(description="Score replay/questions.txt")
    parser.add_argument("--only-field", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    rows = load_rows()
    if args.only_field:
        rows = [row for row in rows if row[0] == args.only_field]
    if args.limit:
        rows = rows[: args.limit]
    corpus = RemoteCorpus()
    chat = QwenChat()
    failed = 0
    for field, said, must, must_not in rows:
        problem, _text = await play_row(field, said, must, must_not, corpus, chat)
        if problem:
            failed += 1
            print(f"FAIL\t{field}\t{said}\t{problem}")
        else:
            print(f"pass\t{field}\t{said}")
    print(f"{len(rows) - failed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())

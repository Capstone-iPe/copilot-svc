"""The input loop and print. Nothing else."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from copilot.chat.qwen_chat import QwenChat
from copilot.config import DEFAULT_INDEX, mcp_url
from copilot.corpus.index_corpus import Corpus
from copilot.onb.mcp_onb import McpOnb, connect
from copilot.say.questions import prompt_for
from copilot.say.redact import redact
from copilot.session import Session
from copilot.words import QUIT


async def run(url: str, index: Path) -> None:
    corpus = Corpus(index)
    client, http, waiter = await connect(url)
    try:
        await _talk(McpOnb(client), corpus)
    finally:
        await client.__aexit__(None, None, None)
        await http.aclose()
        if waiter.server is not None:
            waiter.server.shutdown()


async def _talk(onb: McpOnb, corpus: Corpus) -> None:
    step = await onb.next_step()
    if step.get("error"):
        print(f"ONB did not open an application ({step['error']}).")
        return
    session = Session(QwenChat(), onb, corpus, step["application_id"], step)
    print(prompt_for(step))
    while True:
        line = _read()
        if line is None or line.strip().lower() in QUIT:
            break
        if not line.strip():
            print(prompt_for(session.step))
            continue
        reply = await session.turn(line)
        if reply.text:
            print(redact(reply.text, line))
        if reply.prompt:
            print(reply.prompt)


def _read() -> str | None:
    try:
        return input("> ")
    except EOFError:
        return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    parser = argparse.ArgumentParser(description="Talk to ONB as the copilot.")
    parser.add_argument("--mcp", default=mcp_url())
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    args = parser.parse_args()
    asyncio.run(run(args.mcp, args.index))


if __name__ == "__main__":
    main()

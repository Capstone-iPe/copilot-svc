"""The input loop and print. Nothing else."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from copilot.adapters.cli import CliAdapter
from copilot.chat.qwen_chat import QwenChat
from copilot.config import mcp_url
from copilot.corpus.passages import Passages
from copilot.corpus.remote import RemoteCorpus
from copilot.onb.mcp_onb import McpOnb, connect
from copilot.session import Session
from copilot.words import QUIT


async def run(url: str) -> None:
    corpus = RemoteCorpus()
    client, http, waiter = await connect(url)
    try:
        await _talk(McpOnb(client), corpus)
    finally:
        await client.__aexit__(None, None, None)
        await http.aclose()
        if waiter.server is not None:
            waiter.server.shutdown()


async def _talk(onb: McpOnb, corpus: Passages) -> None:
    adapter = CliAdapter()
    step = await onb.next_step()
    if step.get("error"):
        print(f"ONB did not open an application ({step['error']}).")
        return
    session = Session(QwenChat(), onb, corpus, step["application_id"], step)
    opened = adapter.open(step)
    if opened["prompt"]:
        print(opened["prompt"])
    while True:
        line = _read()
        if line is None or line.strip().lower() in QUIT:
            break
        if not line.strip():
            again = adapter.open(session.step)
            if again["prompt"]:
                print(again["prompt"])
            continue
        out = adapter.render(await session.turn(line), line=line)
        for message in out.get("messages") or []:
            print(message)


def _read() -> str | None:
    try:
        return input("> ")
    except EOFError:
        return None


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)
    logging.getLogger("copilot").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Talk to ONB as the copilot.")
    parser.add_argument("--mcp", default=mcp_url())
    args = parser.parse_args()
    asyncio.run(run(args.mcp))


if __name__ == "__main__":
    main()

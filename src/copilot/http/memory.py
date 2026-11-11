"""Start a Session against in-process ONB. For local HTTP and tests."""

from __future__ import annotations

import sys
from pathlib import Path

from copilot.chat.qwen_chat import QwenChat
from copilot.config import DEFAULT_INDEX
from copilot.corpus.index_corpus import Corpus
from copilot.session import Session


def _memory_onb():
    copilot_svc = Path(__file__).resolve().parents[3]
    onb_src = copilot_svc.parent / "onb-svc" / "src"
    replay = copilot_svc / "replay"
    for path in (onb_src, replay):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    from memory_onb import MemoryOnb

    return MemoryOnb()


async def memory_start() -> tuple[Session, dict]:
    onb = _memory_onb()
    step = await onb.next_step()
    corpus = Corpus(DEFAULT_INDEX)
    session = Session(QwenChat(), onb, corpus, step["application_id"], step)
    return session, step

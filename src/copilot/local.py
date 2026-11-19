"""Local Session factory: in-process ONB. For laptop runs and smoke only.

Not the deploy path. Deploy uses live.py and the FE's Bearer token.
"""

from __future__ import annotations

import sys
from pathlib import Path

from copilot.chat.qwen_chat import QwenChat
from copilot.corpus.remote import RemoteCorpus
from copilot.session import Session


def _memory_onb():
    copilot_svc = Path(__file__).resolve().parents[2]
    onb_src = copilot_svc.parent / "onb-svc" / "src"
    replay = copilot_svc / "replay"
    for path in (onb_src, replay):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    from memory_onb import MemoryOnb

    return MemoryOnb()


async def local_start(bearer: str = "", application_id: str | None = None) -> tuple[Session, dict]:
    del bearer  # MemoryOnb ignores auth; FE still sends a bearer to the API.
    onb = _memory_onb()
    step = await onb.next_step(application_id) if application_id else await onb.next_step()
    corpus = RemoteCorpus()
    session = Session(QwenChat(), onb, corpus, step["application_id"], step)
    return session, step


"""Deploy Session factory: live ONB over MCP. Bearer comes from the FE."""

from __future__ import annotations

import logging

from copilot.chat.qwen_chat import QwenChat
from copilot.config import mcp_url
from copilot.corpus.remote import RemoteCorpus
from copilot.edge import CachedCorpus
from copilot.onb.bearer import AccessToken
from copilot.onb.mcp_onb import LiveOnb
from copilot.session import Session

log = logging.getLogger("copilot")


async def live_start(bearer: str, application_id: str | None = None) -> tuple[Session, dict]:
    token = AccessToken(bearer)
    onb = LiveOnb(mcp_url(), token)
    step = await onb.next_step(application_id) if application_id else await onb.next_step()
    session = Session(QwenChat(), onb, CachedCorpus(RemoteCorpus()), step["application_id"], step)
    session.access_token = token
    log.info("opened live ONB conversation")
    return session, step

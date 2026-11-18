"""Deploy Session factory: live ONB over MCP. Bearer comes from the FE."""

from __future__ import annotations

import logging

from copilot.chat.qwen_chat import QwenChat
from copilot.config import mcp_url
from copilot.corpus.remote import RemoteCorpus
from copilot.onb.bearer import AccessToken
from copilot.onb.mcp_onb import McpOnb, connect_bearer
from copilot.session import Session

log = logging.getLogger("copilot")


async def live_start(bearer: str) -> tuple[Session, dict]:
    token = AccessToken(bearer)
    client, http = await connect_bearer(mcp_url(), token)
    onb = McpOnb(client)
    step = await onb.next_step()
    session = Session(QwenChat(), onb, RemoteCorpus(), step["application_id"], step)
    session.access_token = token
    session._mcp_http = http
    log.info("opened live ONB conversation")
    return session, step

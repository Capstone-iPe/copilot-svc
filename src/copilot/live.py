"""Deploy Session factory: live ONB over MCP with a Google bearer."""

from __future__ import annotations

import logging

from copilot.chat.qwen_chat import QwenChat
from copilot.config import mcp_url
from copilot.corpus.remote import RemoteCorpus
from copilot.onb.bearer import mcp_bearer
from copilot.onb.mcp_onb import McpOnb, connect_bearer
from copilot.session import Session

log = logging.getLogger("copilot")

_onb: McpOnb | None = None
_http = None


async def live_start() -> tuple[Session, dict]:
    onb = await _shared_onb()
    step = await onb.next_step()
    session = Session(QwenChat(), onb, RemoteCorpus(), step["application_id"], step)
    return session, step


async def _shared_onb() -> McpOnb:
    global _onb, _http
    if _onb is not None:
        return _onb
    client, _http = await connect_bearer(mcp_url(), mcp_bearer)
    _onb = McpOnb(client)
    log.info("connected to live ONB MCP")
    return _onb

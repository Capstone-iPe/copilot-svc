"""The real ONB client. Five tools, and the log omits the saved value."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import webbrowser

from copilot.onb.onb_tools import OnbTools
from copilot.onb.sign_in import Tokens, Wait, loopback

log = logging.getLogger("copilot")

# A free Render service answers 502, or drops the connection, while it boots.
# Three short tries stay inside the website's single-request wait.
_DELAYS = (0, 5, 8)
_WAKE = {502, 503, 504}
_HTTP_TIMEOUT = int(os.environ.get("ONB_HTTP_TIMEOUT", "45"))


def tool_payload(result: object) -> dict:
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise RuntimeError("The tool result was empty.")


class McpOnb(OnbTools):
    def __init__(self, client) -> None:
        self.client = client

    async def next_step(self, application_id: str | None = None) -> dict:
        arguments = {} if not application_id else {"application_id": application_id}
        return await call(self.client, "next_step", arguments)

    async def save_answer(self, application_id: str, field: str, value: str) -> dict:
        arguments = {"application_id": application_id, "field": field, "value": value}
        return await call(self.client, "save_answer", arguments)

    async def save_file(self, application_id: str, slot: str, file: str | None = None, missing: bool = False) -> dict:
        arguments: dict = {"application_id": application_id, "slot": slot}
        if missing:
            arguments["missing"] = True
        else:
            arguments["file"] = file
        return await call(self.client, "save_file", arguments)

    async def submit(self, application_id: str) -> dict:
        return await call(self.client, "submit", {"application_id": application_id})

    async def get_review(self, application_id: str) -> dict:
        return await call(self.client, "get_review", {"application_id": application_id})


class LiveOnb(OnbTools):
    """Fresh MCP connect per tool call.

    Streamable HTTP keeps a long-lived SSE session. On Render that stream dies
    between turns, so a held Client works for create and fails on the next message.
    """

    def __init__(self, mcp_url: str, bearer_fn) -> None:
        self.mcp_url = mcp_url
        self.bearer_fn = bearer_fn

    async def next_step(self, application_id: str | None = None) -> dict:
        return await self._run("next_step", application_id)

    async def save_answer(self, application_id: str, field: str, value: str) -> dict:
        return await self._run("save_answer", application_id, field, value)

    async def save_file(
        self,
        application_id: str,
        slot: str,
        file: str | None = None,
        missing: bool = False,
    ) -> dict:
        return await self._run("save_file", application_id, slot, file=file, missing=missing)

    async def submit(self, application_id: str) -> dict:
        return await self._run("submit", application_id)

    async def get_review(self, application_id: str) -> dict:
        return await self._run("get_review", application_id)

    async def _run(self, method: str, *args, **kwargs):
        read_only = method == "get_review" or (method == "next_step" and bool(args[0]))
        last: Exception | None = None
        for delay in _DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                client, http = await connect_bearer(self.mcp_url, self.bearer_fn)
            except OnbAsleep as exc:
                last = exc
                log.info("ONB connect failed (%s); retrying %s", exc, method)
                continue
            try:
                return await getattr(McpOnb(client), method)(*args, **kwargs)
            except Exception as exc:
                last = exc
                # Once dispatched, a write may have succeeded even if its response was lost.
                if not read_only or not await _retry_tool(exc, http, self.mcp_url):
                    raise
                log.info("ONB %s failed while the service wakes; retrying", method)
            finally:
                await client.__aexit__(None, None, None)
                await http.aclose()
        assert last is not None
        raise last


async def call(client, name: str, arguments: dict) -> dict:
    result = tool_payload(await client.call_tool(name, arguments))
    shown = {key: value for key, value in arguments.items() if key not in {"value", "application_id"}}
    if result.get("error"):
        shown["error"] = result["error"]
    log.info("calling tool %s %s", name, shown or {})
    if result.get("error"):
        log.info("tool %s returned error %s", name, result["error"])
    else:
        pending = (result.get("pending") or {}) if isinstance(result.get("pending"), dict) else {}
        log.info("tool %s returned ok pending=%s", name, pending.get("name"))
    return result


async def connect(mcp_url: str):
    """CLI path: Google sign-in in the browser, then MCP."""
    import httpx2
    from mcp import Implementation
    from mcp.client.client import Client
    from mcp.client.streamable_http import streamable_http_client

    redirect_uri, waiter = loopback()
    auth = _auth(mcp_url, redirect_uri, waiter)
    http = httpx2.AsyncClient(auth=auth, follow_redirects=False, timeout=60)
    transport = streamable_http_client(mcp_url, http_client=http)
    client = Client(transport, client_info=Implementation(name="ipe-copilot", version="0.0.2"))
    await client.__aenter__()
    return client, http, waiter


async def connect_bearer(mcp_url: str, bearer_fn):
    """Server path: live ONB with the FE's Google access token. No refresh here.

    bearer_fn is a zero-arg callable that returns the current access token.
    """
    import httpx2
    from mcp import Implementation
    from mcp.client.client import Client
    from mcp.client.streamable_http import streamable_http_client

    class _Bearer(httpx2.Auth):
        def auth_flow(self, request):
            request.headers["Authorization"] = f"Bearer {bearer_fn()}"
            yield request

    http = httpx2.AsyncClient(auth=_Bearer(), follow_redirects=False, timeout=_HTTP_TIMEOUT)
    transport = streamable_http_client(mcp_url, http_client=http)
    client = Client(transport, client_info=Implementation(name="ipe-copilot", version="0.0.2"))
    try:
        await client.__aenter__()
    except Exception as exc:
        # mcp 2.3 maps HTTP 401 to a generic MCPError ("Server returned an error
        # response") that hides invalid_token. Probe once so callers can tell auth apart.
        status = await _mcp_status(http, mcp_url)
        await http.aclose()
        if status in (401, 403):
            raise RuntimeError("invalid_token: ONB rejected the Google access token") from exc
        if status in _WAKE or status is None:
            raise OnbAsleep(status) from exc
        raise
    return client, http


class OnbAsleep(Exception):
    """ONB's front door returned a start-up page, or the connection never opened."""

    def __init__(self, status: int | None) -> None:
        self.status = status
        shown = "unreachable" if status is None else str(status)
        super().__init__(f"ONB is waking up ({shown})")


def _transport_failure(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "invalid_token" in text or "401" in text or "403" in text:
        return False
    if any(part in name for part in ("timeout", "connect", "network", "protocol")):
        return True
    return any(part in text for part in ("timed out", "timeout", "connection reset", "connect error"))


async def _retry_tool(exc: BaseException, http, mcp_url: str) -> bool:
    if "invalid_token" in str(exc).lower():
        return False
    status = await _mcp_status(http, mcp_url)
    if status in (401, 403):
        return False
    if status in _WAKE or status is None:
        return True
    return _transport_failure(exc)


async def _mcp_status(http, mcp_url: str) -> int | None:
    """POST a tiny initialize; return the HTTP status, or None if the probe itself failed."""
    try:
        response = await http.post(
            mcp_url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "ipe-copilot", "version": "0.0.2"},
                },
            },
        )
        return response.status_code
    except Exception:
        return None


def _auth(mcp_url: str, redirect_uri: str, waiter: Wait):
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    return OAuthClientProvider(
        server_url=mcp_url,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[redirect_uri],
            client_name="iPe copilot",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="openid email",
            token_endpoint_auth_method="client_secret_post",
        ),
        storage=Tokens(),
        redirect_handler=_redirect,
        callback_handler=lambda: _callback(waiter),
    )


async def _redirect(url: str) -> None:
    print("Opening the browser to sign in with Google.")
    print(url)
    webbrowser.open(url)


async def _callback(waiter: Wait):
    from mcp.shared.auth import AuthorizationCodeResult

    await asyncio.to_thread(waiter.ready.wait)
    if waiter.box.get("error") or not waiter.box.get("code"):
        raise RuntimeError(waiter.box.get("error") or "Google sign-in did not return a code.")
    return AuthorizationCodeResult(
        code=waiter.box["code"],
        state=waiter.box["state"],
        iss=waiter.box["iss"],
    )

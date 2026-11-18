"""The real ONB client. Five tools, and the log omits the saved value."""

from __future__ import annotations

import asyncio
import json
import logging
import webbrowser

from copilot.onb.onb_tools import OnbTools
from copilot.onb.sign_in import Tokens, Wait, loopback

log = logging.getLogger("copilot")


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


async def call(client, name: str, arguments: dict) -> dict:
    result = tool_payload(await client.call_tool(name, arguments))
    shown = {key: value for key, value in arguments.items() if key not in {"value", "application_id"}}
    if result.get("error"):
        shown["error"] = result["error"]
    log.debug("tool %s %s", name, shown)
    return result


async def connect(mcp_url: str):
    import httpx2
    from mcp import Implementation
    from mcp.client.auth import OAuthClientProvider
    from mcp.client.client import Client
    from mcp.client.streamable_http import streamable_http_client

    redirect_uri, waiter = loopback()
    auth = _auth(mcp_url, redirect_uri, waiter)
    http = httpx2.AsyncClient(auth=auth, follow_redirects=False, timeout=60)
    transport = streamable_http_client(mcp_url, http_client=http)
    client = Client(transport, client_info=Implementation(name="ipe-copilot", version="0.0.2"))
    await client.__aenter__()
    return client, http, waiter


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

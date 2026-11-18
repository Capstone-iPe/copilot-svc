"""Google access token for live ONB MCP. No browser on the server."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_cached: tuple[str, float] | None = None


def mcp_bearer() -> str:
    """Bearer ONB accepts: a Google access token that Google still validates."""
    direct = os.environ.get("ONB_MCP_BEARER", "").strip()
    if direct:
        return direct
    return _refreshed()


def _refreshed() -> str:
    global _cached
    now = time.time()
    if _cached and _cached[1] > now + 60:
        return _cached[0]
    refresh = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not refresh or not client_id or not client_secret:
        raise RuntimeError(
            "Live ONB needs ONB_MCP_BEARER, or GOOGLE_REFRESH_TOKEN + GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET."
        )
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode()
    request = urllib.request.Request(
        _GOOGLE_TOKEN,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google refresh failed: {detail}") from exc
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise RuntimeError("Google refresh returned no access_token.")
    expires_in = int(payload.get("expires_in") or 3500)
    _cached = (access, now + expires_in)
    return access

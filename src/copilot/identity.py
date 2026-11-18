"""Who the Google access token belongs to. Used for the opening greeting only."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger("copilot")

USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def merchant_call_name(access_token: str) -> str | None:
    """First name from Google userinfo, or None when the token is not a Google access token."""
    text = (access_token or "").strip()
    if not text:
        return None
    try:
        profile = _userinfo(text)
    except ValueError:
        return None
    for key in ("given_name", "name"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().split()[0]
    return None


def _userinfo(access_token: str) -> dict:
    request = urllib.request.Request(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        log.debug("google userinfo failed: %s", exc)
        raise ValueError("google userinfo failed") from exc
    if not isinstance(payload, dict):
        raise ValueError("google userinfo failed")
    return payload

"""Validate the Google access token and derive the merchant identity."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlencode

log = logging.getLogger("copilot")

USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


@dataclass(frozen=True)
class Merchant:
    id: str
    name: str | None = None


def verify_merchant(access_token: str, audiences: frozenset[str]) -> Merchant | None:
    try:
        info = _get_json(f"{TOKENINFO_URL}?{urlencode({'access_token': access_token})}")
        if (info.get("aud") or info.get("azp")) not in audiences:
            return None
        profile = _userinfo(access_token)
    except (ValueError, TypeError):
        return None
    subject = profile.get("sub")
    if not isinstance(subject, str) or not subject.strip() or profile.get("email_verified") not in (True, "true"):
        return None
    if (token_subject := info.get("sub")) is not None and token_subject != subject:
        return None
    return Merchant(f"google:{subject}", _call_name(profile))


def merchant_call_name(access_token: str) -> str | None:
    """First name from Google userinfo, or None when the token is not a Google access token."""
    text = (access_token or "").strip()
    if not text:
        return None
    try:
        profile = _userinfo(text)
    except (ValueError, TypeError):
        return None
    return _call_name(profile)


def _call_name(profile: dict) -> str | None:
    for key in ("given_name", "name"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().split()[0]
    return None


def _userinfo(access_token: str) -> dict:
    return _get_json(USERINFO_URL, access_token)


def _get_json(url: str, access_token: str = "") -> dict:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"} if access_token else {},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        log.debug("Google token verification request failed (%s)", type(exc).__name__)
        raise ValueError("Google token verification failed") from exc
    if not isinstance(payload, dict):
        raise TypeError("Google returned a non-object response")
    return payload

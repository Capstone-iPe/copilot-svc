"""Opening welcome matches the prototype; name comes from Google userinfo."""

import asyncio

import pytest
from fastapi import HTTPException

from copilot.app import _authenticate
from copilot.identity import AudienceRejected, Merchant, merchant_call_name, verify_merchant
from copilot.say.greeting import welcome_text


def test_welcome_without_name_matches_prototype() -> None:
    text = welcome_text()
    assert text == "Welcome to iPe. I'll ask for each part of the application one at a time."


def test_welcome_with_name_is_personal() -> None:
    assert welcome_text("Rupesh").startswith("Hi Rupesh, welcome to iPe.")


def test_call_name_prefers_given_name(monkeypatch) -> None:
    def fake_userinfo(_token: str) -> dict:
        return {"given_name": "Rupesh Sasne", "name": "Other"}

    monkeypatch.setattr("copilot.identity._userinfo", fake_userinfo)
    assert merchant_call_name("ya29.token") == "Rupesh"


def test_call_name_falls_back_to_full_name(monkeypatch) -> None:
    def fake_userinfo(_token: str) -> dict:
        return {"name": "Ada Lovelace"}

    monkeypatch.setattr("copilot.identity._userinfo", fake_userinfo)
    assert merchant_call_name("ya29.token") == "Ada"


def test_call_name_none_when_userinfo_fails(monkeypatch) -> None:
    def boom(_token: str) -> dict:
        raise ValueError("nope")

    monkeypatch.setattr("copilot.identity._userinfo", boom)
    assert merchant_call_name("not-google") is None


@pytest.mark.parametrize(("audience", "token_subject", "verified", "expected"), [
    ("web", "123", True, Merchant("google:123", "Ada")),
    ("other", "123", True, AudienceRejected),
    ("web", "456", True, None),
    ("web", "123", False, None),
])
def test_merchant_requires_the_allowed_audience_and_a_verified_subject(
    monkeypatch, audience, token_subject, verified, expected,
) -> None:
    monkeypatch.setattr("copilot.identity._get_json", lambda _url: {"aud": audience, "sub": token_subject})
    monkeypatch.setattr("copilot.identity._userinfo", lambda _token: {
        "sub": "123", "email_verified": verified, "given_name": "Ada Lovelace",
    })
    if expected is AudienceRejected:
        with pytest.raises(AudienceRejected):
            verify_merchant("google-token", frozenset({"web"}))
        return
    assert verify_merchant("google-token", frozenset({"web"})) == expected


def test_a_token_for_another_client_is_forbidden() -> None:
    class State:
        @staticmethod
        def verify(_token: str) -> Merchant:
            raise AudienceRejected()

    class App:
        state = State()

    class Req:
        app = App()

    with pytest.raises(HTTPException) as caught:
        asyncio.run(_authenticate(Req(), "Bearer ya29.other", None))
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "forbidden"

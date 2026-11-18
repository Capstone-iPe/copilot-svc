"""Opening welcome matches the prototype; name comes from Google userinfo."""

from copilot.identity import merchant_call_name
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

"""First assistant lines. Matches the prototype welcome, with an optional name."""

from __future__ import annotations


def welcome_text(merchant_name: str | None = None) -> str:
    """Greeting only. The first ONB question is a separate message."""
    if merchant_name:
        return (
            f"Hi {merchant_name}, welcome to iPe. "
            "I'll ask for each part of the application one at a time."
        )
    return "Welcome to iPe. I'll ask for each part of the application one at a time."

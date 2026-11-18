"""First assistant line. Matches the prototype welcome, with an optional name."""

from __future__ import annotations


def opening_text(question: str, merchant_name: str | None = None) -> str:
    """Welcome + the first ONB question in one assistant message."""
    if merchant_name:
        greet = (
            f"Hi {merchant_name}, welcome to iPe. "
            "I'll ask for each part of the application one at a time."
        )
    else:
        greet = "Welcome to iPe. I'll ask for each part of the application one at a time."
    ask = (question or "").strip()
    return f"{greet} {ask}".strip() if ask else greet

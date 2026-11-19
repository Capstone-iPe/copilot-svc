"""First assistant lines. Matches the prototype welcome, with an optional name."""

from __future__ import annotations


def welcome_back(merchant_name: str | None, snapshot: dict) -> str:
    """Return visit. The next question is a separate message, same as the first open."""
    answers = snapshot.get("answers") if isinstance(snapshot.get("answers"), dict) else {}
    shop = str(answers.get("shop_name") or "").strip()
    done = [name.replace("_", " ") for name, value in answers.items() if value]
    who = f"Welcome back, {merchant_name}." if merchant_name else "Welcome back."
    if shop:
        filled = ", ".join(done)
        return f"{who} So far for {shop}: {filled}."
    if done:
        return f"{who} So far: {', '.join(done)}."
    return who


def welcome_text(merchant_name: str | None = None) -> str:
    """Greeting only. The first ONB question is a separate message."""
    if merchant_name:
        return (
            f"Hi {merchant_name}, welcome to iPe. "
            "I'll ask for each part of the application one at a time."
        )
    return "Welcome to iPe. I'll ask for each part of the application one at a time."

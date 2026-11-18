"""Access token the FE sends. Copilot does not refresh Google."""

from __future__ import annotations


class AccessToken:
    """Mutable bearer for one conversation. FE may refresh; we just swap the value."""

    def __init__(self, value: str) -> None:
        self.value = value.strip()

    def __call__(self) -> str:
        if not self.value:
            raise RuntimeError("missing_bearer")
        return self.value

    def set(self, value: str) -> None:
        text = value.strip()
        if not text:
            raise RuntimeError("missing_bearer")
        self.value = text

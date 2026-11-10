"""Which uploads are still open."""

from __future__ import annotations


def slot_states(snapshot: dict) -> dict[str, list[str]]:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    states: dict[str, list[str]] = {"open": [], "missing": []}
    for slot, file in files.items():
        state = file.get("state") if isinstance(file, dict) else None
        if state == "missing":
            states["missing"].append(slot)
        elif state != "accepted":
            states["open"].append(slot)
    return states

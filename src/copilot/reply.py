"""What one turn gives back. The terminal prints it. This file does not."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Reply:
    text: str
    prompt: str
    trace: dict
    step: dict

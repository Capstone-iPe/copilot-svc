"""Never print back a digit run the merchant just typed."""

from __future__ import annotations

import re

from copilot.words import DIGITS, VOLUME

_ACK = re.compile(r"^(?:Got it,|No problem, I've updated)", re.I)


def redact(text: str, line: str) -> str:
    if VOLUME.fullmatch(line.strip()) and _ACK.match(text.strip()):
        return text
    typed = [re.sub(r"\D", "", found) for found in DIGITS.findall(line)]
    if not typed:
        return text

    def hide(match: re.Match) -> str:
        if text[max(0, match.start() - 3) : match.start()] == "MR-":
            return match.group(0)
        digits = re.sub(r"\D", "", match.group(0))
        return "[number hidden]" if any(digits in run or run in digits for run in typed) else match.group(0)

    return DIGITS.sub(hide, text)

"""ONB in this process. The replay uses it so a run does not sign in."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from onb.intake.cases import ask, get_review, save_answer, save_file, submit
    from onb.store.memory_application_store import MemoryApplicationStore
except ModuleNotFoundError:
    _ONB = Path(__file__).resolve().parents[2] / "onb-svc" / "src"
    if str(_ONB) not in sys.path:
        sys.path.insert(0, str(_ONB))
    from onb.intake.cases import ask, get_review, save_answer, save_file, submit
    from onb.store.memory_application_store import MemoryApplicationStore

from copilot.onb.onb_tools import OnbTools


class MemoryOnb(OnbTools):
    def __init__(self) -> None:
        self.store = MemoryApplicationStore()

    async def next_step(self, application_id: str | None = None) -> dict:
        return ask(self.store, application_id)

    async def save_answer(self, application_id: str, field: str, value: str) -> dict:
        return save_answer(self.store, application_id, field, value)

    async def save_file(
        self,
        application_id: str,
        slot: str,
        file: str | None = None,
        missing: bool = False,
    ) -> dict:
        return save_file(self.store, application_id, slot, file, missing)

    async def submit(self, application_id: str) -> dict:
        return submit(self.store, application_id)

    async def get_review(self, application_id: str) -> dict:
        return get_review(self.store, application_id)

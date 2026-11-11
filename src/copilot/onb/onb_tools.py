"""The five ONB tools. Nothing else."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class OnbTools(Protocol):
    async def next_step(self, application_id: str | None = None) -> dict: ...

    async def save_answer(self, application_id: str, field: str, value: str) -> dict: ...

    async def save_file(
        self,
        application_id: str,
        slot: str,
        file: str | None = None,
        missing: bool = False,
    ) -> dict: ...

    async def submit(self, application_id: str) -> dict: ...

    async def get_review(self, application_id: str) -> dict: ...

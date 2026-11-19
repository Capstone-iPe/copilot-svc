"""Conversation acts: small talk is not saved, a correction does not fill the pending field."""

import asyncio

from copilot.chat.chat_model import ChatModel
from copilot.corpus.passages import Passages
from copilot.onb.onb_tools import OnbTools
from copilot.session import Session


class Boom(ChatModel):
    def complete(self, messages, max_tokens, schema=None):
        raise AssertionError("the model must not be called")


class Quiet(Passages):
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.document_ids: set[str] = set()

    def search(self, query, k=4):
        return []


class Shop(OnbTools):
    """Pending advances only when the pending field is saved. A stored field can be corrected."""

    def __init__(self) -> None:
        self.order = ["shop_name", "city", "business_type"]
        self.index = 0
        self.answers: dict[str, str] = {}
        self.calls: list[tuple] = []

    def _step(self) -> dict:
        name = self.order[self.index] if self.index < len(self.order) else None
        pending = {"kind": "field", "name": name} if name else None
        return {
            "application_id": "app_1",
            "pending": pending,
            "snapshot": {"answers": dict(self.answers), "files": {}},
        }

    async def next_step(self, application_id=None):
        self.calls.append(("next_step", application_id))
        return self._step()

    async def save_answer(self, application_id, field, value):
        self.calls.append(("save_answer", field, value))
        pending = self.order[self.index] if self.index < len(self.order) else None
        if field != pending and field not in self.answers:
            return {"error": "field_not_pending"}
        self.answers[field] = value
        if field == pending:
            self.index += 1
        return {"field": field, "value": value}

    async def save_file(self, application_id, slot, file=None, missing=False):
        return {}

    async def submit(self, application_id):
        return {}

    async def get_review(self, application_id):
        return {}


def _session(onb: Shop | None = None, step: dict | None = None) -> tuple[Session, Shop]:
    onb = onb or Shop()
    step = step or asyncio.run(onb.next_step())
    return Session(Boom(), onb, Quiet(), "app_1", step), onb


def test_a_name_and_city_in_one_line_are_saved_in_order() -> None:
    session, onb = _session()

    reply = asyncio.run(session.turn("Sharma Sweets in Pune"))

    assert onb.answers == {"shop_name": "Sharma Sweets", "city": "Pune"}
    assert onb.index == 2
    assert "Got it, Sharma Sweets." in reply.text
    assert "Got it, Pune." in reply.text
    assert "city" not in reply.prompt.lower() or "kind of shop" in reply.prompt.lower()
    assert reply.step["pending"]["name"] == "business_type"


def test_a_correction_does_not_overwrite_the_pending_city() -> None:
    onb = Shop()
    onb.answers = {"shop_name": "Sarma"}
    onb.index = 1
    session, onb = _session(onb, asyncio.run(onb.next_step()))

    reply = asyncio.run(session.turn("sorry, the shop name should be Sharma"))

    assert onb.answers["shop_name"] == "Sharma"
    assert "city" not in onb.answers
    assert onb.index == 1
    assert reply.step["pending"]["name"] == "city"
    assert "shop name" in reply.text.lower()


def test_small_talk_is_not_stored() -> None:
    session, onb = _session()

    reply = asyncio.run(session.turn("ok"))

    assert onb.answers == {}
    assert not any(call[0] == "save_answer" for call in onb.calls)
    assert reply.step["pending"]["name"] == "shop_name"


def test_why_not_cafe_is_the_shop_name() -> None:
    session, onb = _session()

    asyncio.run(session.turn("Why Not Cafe"))

    assert onb.answers["shop_name"] == "Why Not Cafe"


def test_a_city_and_a_why_save_only_the_city() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Sharma Sweets"}
    session, onb = _session(onb, asyncio.run(onb.next_step()))

    reply = asyncio.run(session.turn("Pune, but why"))

    assert onb.answers["city"] == "Pune"
    assert "but why" not in onb.answers["city"]
    assert reply.text.startswith("Got it, Pune.")

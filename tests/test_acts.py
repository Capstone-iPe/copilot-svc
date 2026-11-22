"""Conversation acts: small talk is not saved, a correction does not fill the pending field."""

import asyncio

from copilot.chat.chat_model import ChatModel
from copilot.dialogue import DialogueState
from copilot.corpus.passages import Passages
from copilot.onb.onb_tools import OnbTools
from copilot.say.questions import prompt_for
from copilot.session import Session


class Boom(ChatModel):
    def complete(self, messages, max_tokens, schema=None):
        raise AssertionError("the model must not be called")


class Scripted(ChatModel):
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def complete(self, messages, max_tokens, schema=None):
        self.calls += 1
        return self.reply


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


def _session(onb: Shop | None = None, step: dict | None = None, chat: ChatModel | None = None) -> tuple[Session, Shop]:
    onb = onb or Shop()
    step = step or asyncio.run(onb.next_step())
    return Session(chat or Boom(), onb, Quiet(), "app_1", step), onb


def test_an_unreadable_volume_asks_for_digits() -> None:
    class Volume(Shop):
        def __init__(self) -> None:
            super().__init__()
            self.order = ["monthly_volume"]

        async def save_answer(self, application_id, field, value):
            self.calls.append(("save_answer", field, value))
            return {"error": "volume_unreadable"}

    onb = Volume()
    note = '{"acts":[{"type":"answer","field":"monthly_volume","value_span":"120K"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("120K"))

    assert "digits" in reply.text.lower()
    assert "city is Pune" not in reply.text
    assert onb.answers == {}
    assert reply.step["pending"]["name"] == "monthly_volume"


def test_a_plain_city_is_read_by_the_model() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Sharma Sweets"}
    note = '{"acts":[{"type":"answer","field":"city","value_span":"Pune"}],"confidence":"high"}'
    chat = Scripted(note)
    session, onb = _session(onb, asyncio.run(onb.next_step()), chat)

    asyncio.run(session.turn("Pune"))

    assert chat.calls == 1
    assert onb.answers["city"] == "Pune"


def test_a_name_and_city_in_one_line_are_saved_in_order() -> None:
    note = (
        '{"acts":['
        '{"type":"answer","field":"shop_name","value_span":"Sharma Sweets"},'
        '{"type":"answer","field":"city","value_span":"Pune"}'
        '],"confidence":"high"}'
    )
    session, onb = _session(chat=Scripted(note))

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
    note = '{"acts":[{"type":"correct","field":"shop_name","value_span":"Sharma"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("sorry, the shop name should be Sharma"))

    assert onb.answers["shop_name"] == "Sharma"
    assert "city" not in onb.answers
    assert onb.index == 1
    assert reply.step["pending"]["name"] == "city"
    assert "shop name" in reply.text.lower()


def test_a_typo_after_wait_is_not_a_pause() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Sasane Gift Shop"}
    session, onb = _session(onb, asyncio.run(onb.next_step()))

    reply = asyncio.run(session.turn("wait, there is a typo in shop's name"))

    assert "take your time" not in reply.text.lower()
    assert "shop name" in reply.text.lower()
    assert "city" not in onb.answers


def test_small_talk_is_not_stored() -> None:
    chat = Scripted('{"acts":[{"type":"chitchat"}],"confidence":"high"}')
    session, onb = _session(chat=chat)

    reply = asyncio.run(session.turn("ok"))

    assert chat.calls == 1

    assert onb.answers == {}
    assert not any(call[0] == "save_answer" for call in onb.calls)
    assert reply.step["pending"]["name"] == "shop_name"


def test_why_not_cafe_is_the_shop_name() -> None:
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"Why Not Cafe"}],"confidence":"high"}'
    chat = Scripted(note)
    session, onb = _session(chat=chat)

    asyncio.run(session.turn("Why Not Cafe"))

    assert chat.calls == 1

    assert onb.answers["shop_name"] == "Why Not Cafe"


def test_a_wrong_model_label_is_not_saved_as_the_city() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Balaji Supermarket"}
    note = (
        '{"acts":[{"type":"answer","field":"city","value_span":"there was a typo in shop name"}],'
        '"confidence":"high"}'
    )
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("there was a typo in shop name"))

    assert "city" not in onb.answers
    assert "shop name" in reply.text.lower()


def test_a_typo_remark_is_not_stored_as_the_pending_field() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Balaji Supermarket"}
    session, onb = _session(onb, asyncio.run(onb.next_step()))

    reply = asyncio.run(session.turn("there was a typo in shop name"))

    assert "city" not in onb.answers
    assert onb.answers["shop_name"] == "Balaji Supermarket"
    assert "shop name" in reply.text.lower()
    assert reply.prompt == "What is the shop's legal name?"

    session.chat = Scripted(
        '{"acts":[{"type":"correct","field":"shop_name","value_span":"Balaji Supermart"}],"confidence":"high"}'
    )
    reply = asyncio.run(session.turn("Balaji Supermart"))

    assert onb.answers["shop_name"] == "Balaji Supermart"
    assert "city" not in onb.answers
    assert reply.step["pending"]["name"] == "city"


def test_a_typo_remark_is_not_refused_as_the_business_type() -> None:
    onb = Shop()
    onb.index = 2
    onb.answers = {"shop_name": "Balaji Supermart", "city": "Pune"}
    session, onb = _session(onb, asyncio.run(onb.next_step()))

    reply = asyncio.run(session.turn("There was a typo in shop name"))

    assert onb.answers == {"shop_name": "Balaji Supermart", "city": "Pune"}
    assert "kind of shop" not in reply.text.lower()
    assert "shop name" in reply.text.lower()


def test_a_recap_reads_the_snapshot_and_not_the_policies() -> None:
    onb = Shop()
    onb.index = 2
    onb.answers = {"shop_name": "Balaji Supermart", "city": "Pune"}
    session, _onb = _session(onb, asyncio.run(onb.next_step()))

    reply = asyncio.run(session.turn("what values have you captured so far?"))

    assert "Balaji Supermart" in reply.text
    assert "Pune" in reply.text
    assert "policies" not in reply.text.lower()


def test_a_city_and_a_why_save_only_the_city() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Sharma Sweets"}
    note = (
        '{"acts":['
        '{"type":"answer","field":"city","value_span":"Pune"},'
        '{"type":"why","field":"city"}'
        '],"confidence":"high"}'
    )
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("Pune, but why"))

    assert onb.answers["city"] == "Pune"
    assert "but why" not in onb.answers["city"]
    assert reply.text.startswith("Got it, Pune.")


def test_a_later_line_is_not_an_old_confirmation() -> None:
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"Pune"}],"confidence":"high"}'
    chat = Scripted(note)
    session, onb = _session(chat=chat)
    session.dialogue.awaiting = "confirm:shop_name"
    session.dialogue.proposed = {"field": "shop_name", "value": "Nope Stores"}

    reply = asyncio.run(session.turn("Pune"))

    assert chat.calls == 1

    assert onb.answers["shop_name"] == "Pune"
    assert session.dialogue.awaiting is None
    assert "Nope" not in reply.text


def test_never_mind_does_not_save_the_new_value() -> None:
    chat = Scripted('{"acts":[{"type":"confirm_no"}],"confidence":"high"}')
    session, onb = _session(chat=chat)
    session.dialogue.awaiting = "value_for:shop_name"

    reply = asyncio.run(session.turn("never mind"))

    assert chat.calls == 1

    assert onb.answers == {}
    assert "leave that" in reply.text.lower()


def test_ok_thanks_is_not_a_shop_name() -> None:
    chat = Scripted('{"acts":[{"type":"chitchat"}],"confidence":"high"}')
    session, onb = _session(chat=chat)

    reply = asyncio.run(session.turn("ok thanks"))

    assert chat.calls == 1

    assert onb.answers == {}
    assert "welcome" in reply.text.lower()


def test_so_far_so_good_is_not_a_recap() -> None:
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"so far so good"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))

    reply = asyncio.run(session.turn("so far so good"))

    assert onb.answers["shop_name"] == "so far so good"
    assert not reply.text.startswith("So far,")


def test_a_later_field_is_not_stored_quietly() -> None:
    note = '{"acts":[{"type":"answer","field":"monthly_volume","value_span":"9 lakh"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))

    reply = asyncio.run(session.turn("volume is 9 lakh"))

    assert onb.answers == {}
    assert "monthly volume" in reply.text.lower()
    assert "current answer" in reply.text.lower()


def test_undo_asks_for_the_last_saved_field() -> None:
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"Sharma Sweets"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))
    asyncio.run(session.turn("Sharma Sweets"))
    session.chat = Scripted('{"acts":[{"type":"undo"}],"confidence":"high"}')

    reply = asyncio.run(session.turn("please undo that last answer"))

    assert onb.answers["shop_name"] == "Sharma Sweets"
    assert "shop name" in reply.text.lower()
    assert session.dialogue.awaiting == "value_for:shop_name"


def test_an_invented_field_name_still_saves_the_shop_kind() -> None:
    onb = Shop()
    onb.order = ["business_type"]
    note = '{"acts":[{"type":"correct","field":"shop_type","value_span":"Retail","canonical":null}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("Retail"))

    assert onb.answers["business_type"] == "retail"
    assert reply.text.startswith("Got it, retail.")


def test_an_invented_field_name_does_not_save_a_correction_as_the_city() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Puma"}
    note = (
        '{"acts":[{"type":"correct","field":"shop_type","value_span":"oh.. that wasn\'t shop\'s name"}],'
        '"confidence":"high"}'
    )
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    asyncio.run(session.turn("oh.. that wasn't shop's name"))

    assert onb.answers == {"shop_name": "Puma"}


def test_a_why_copied_from_an_earlier_turn_does_not_replace_the_city() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Puma"}
    note = '{"acts":[{"type":"why","field":"city","value_span":"why do you need that?"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("Pune"))

    assert onb.answers["city"] == "Pune"
    assert reply.text.startswith("Got it, Pune.")


def test_a_denial_of_the_shop_name_is_not_saved_as_the_city() -> None:
    onb = Shop()
    onb.answers = {"shop_name": "FooBar"}
    onb.index = 1
    note = '{"acts":[{"type":"change_request","field":"shop_name"}],"confidence":"high"}'
    chat = Scripted(note)
    session, onb = _session(onb, asyncio.run(onb.next_step()), chat)

    reply = asyncio.run(session.turn("oh.. that wasn't shop's name"))

    assert chat.calls == 1
    assert onb.answers == {"shop_name": "FooBar"}
    assert "shop name" in reply.text.lower()
    assert reply.step["pending"]["name"] == "city"


def test_a_bad_city_read_of_the_shop_name_is_not_saved() -> None:
    onb = Shop()
    onb.answers = {"shop_name": "FooBar"}
    onb.index = 1
    note = (
        '{"acts":[{"type":"answer","field":"city","value_span":"oh.. that wasn\'t shop\'s name"}],'
        '"confidence":"high"}'
    )
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("oh.. that wasn't shop's name"))

    assert "city" not in onb.answers
    assert onb.answers["shop_name"] == "FooBar"
    assert "shop name" in reply.text.lower()


def test_the_first_question_stays_canonical() -> None:
    step = {"pending": {"kind": "field", "name": "shop_name"}, "snapshot": {"answers": {}, "files": {}}}
    assert prompt_for(step) == "What is the shop's legal name?"


def test_a_later_question_counts_and_starts_lower() -> None:
    step = {
        "pending": {"kind": "field", "name": "city"},
        "snapshot": {"answers": {"shop_name": "Sharma Sweets"}, "files": {}},
    }
    shown = prompt_for(step)
    assert shown.startswith("That's 1 of 7. Next, ")
    assert "Next, W" not in shown
    assert "city" in shown.lower()


def test_almost_done_keeps_a_capital_question() -> None:
    step = {
        "pending": {"kind": "field", "name": "payment_methods"},
        "snapshot": {
            "answers": {
                "shop_name": "Sharma Sweets",
                "city": "Pune",
                "business_type": "retail",
                "monthly_volume": "120000",
            },
            "files": {},
        },
    }
    shown = prompt_for(step)
    assert "Almost done. Which" in shown


def test_a_finished_form_lists_answers_before_submit() -> None:
    step = {
        "pending": None,
        "snapshot": {
            "answers": {"shop_name": "Sharma Sweets", "city": "Pune", "monthly_volume": "120000"},
            "files": {
                "bank_proof": {"state": "accepted"},
                "dpa_addendum": {"state": "missing"},
            },
        },
    }
    shown = prompt_for(step)
    assert "Here's what I have for Sharma Sweets:" in shown
    assert "120000" in shown
    assert "missing" in shown.lower()
    assert "shall I submit" in shown


def test_a_dhaba_is_stored_as_a_restaurant() -> None:
    onb = Shop()
    onb.order = ["business_type"]
    note = '{"acts":[{"type":"answer","field":"business_type","value_span":"it\'s a dhaba","canonical":null}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("it's a dhaba"))

    assert onb.answers["business_type"] == "restaurant"
    assert reply.text.startswith("Got it, dhaba (listed as restaurant).")


def test_a_salon_is_stored_as_salon() -> None:
    onb = Shop()
    onb.order = ["business_type"]
    note = '{"acts":[{"type":"answer","field":"business_type","value_span":"a salon","canonical":null}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    asyncio.run(session.turn("a salon"))

    assert onb.answers["business_type"] == "salon"


def test_upi_and_cash_are_stored_as_the_list() -> None:
    onb = Shop()
    onb.order = ["payment_methods"]
    note = (
        '{"acts":['
        '{"type":"answer","field":"payment_methods","value_span":"UPI","canonical":"upi"},'
        '{"type":"answer","field":"payment_methods","value_span":"cash","canonical":"cash"}'
        '],"confidence":"high"}'
    )
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    asyncio.run(session.turn("UPI and cash both"))

    assert onb.answers["payment_methods"] == "UPI, cash"


def test_a_negated_dhaba_is_not_stored() -> None:
    onb = Shop()
    onb.order = ["business_type"]
    note = '{"acts":[{"type":"answer","field":"business_type","value_span":"dhaba","canonical":"restaurant"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("we aren't a dhaba"))

    assert onb.answers == {}
    assert "kind of shop" in reply.text.lower()


def test_direct_yes_and_no_for_payer_phones() -> None:
    onb = Shop()
    onb.order = ["stores_payer_phones"]
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(""))
    reply = asyncio.run(session.turn("yes"))
    assert onb.answers.get("stores_payer_phones") in {"Yes", "yes"}


def test_store_them_is_not_a_yes() -> None:
    onb = Shop()
    onb.order = ["stores_payer_phones"]
    note = (
        '{"acts":[{"type":"answer","field":"stores_payer_phones","value_span":"we do store them","canonical":"yes"}],'
        '"confidence":"high"}'
    )
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("we do store them"))

    assert onb.answers == {}
    assert "yes or no" in reply.text.lower()


def test_a_named_city_correction_is_stored() -> None:
    onb = Shop()
    onb.index = 2
    onb.answers = {"shop_name": "Blue Anchor Dhaba", "city": "Mumbay"}
    note = '{"acts":[{"type":"change_request","field":"city"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("sorry, the city is Mumbai, not Mumbay"))

    assert onb.answers["city"] == "Mumbai"
    assert "business_type" not in onb.answers
    assert "Mumbai" in reply.text
    assert reply.step["pending"]["name"] == "business_type"


def test_a_named_shop_correction_is_stored() -> None:
    onb = Shop()
    onb.index = 2
    onb.answers = {"shop_name": "Ribbon Reel", "city": "Pune"}
    note = '{"acts":[{"type":"change_request"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    asyncio.run(session.turn("sorry, the shop name is Ribbon Reel Gifts, not Ribbon Reel"))

    assert onb.answers["shop_name"] == "Ribbon Reel Gifts"
    assert "business_type" not in onb.answers


def test_the_first_spelling_restores_the_first_name() -> None:
    session, onb = _session(chat=Scripted(
        '{"acts":[{"type":"answer","field":"shop_name","value_span":"Field Day Sports"}],"confidence":"high"}'
    ))
    asyncio.run(session.turn("Field Day Sports"))
    session.chat = Scripted('{"acts":[{"type":"change_request","field":"shop_name"}],"confidence":"high"}')
    asyncio.run(session.turn("sorry, the shop name is Field Day Sporting"))
    session.chat = Scripted(
        '{"acts":[{"type":"answer","field":"business_type","value_span":"the first spelling"}],"confidence":"high"}'
    )

    reply = asyncio.run(session.turn("the first spelling"))

    assert onb.answers["shop_name"] == "Field Day Sports"
    assert "first spelling" not in onb.answers.values()
    assert "Field Day Sports" in reply.text


def test_the_earlier_one_restores_the_previous_city() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Moonjar Sweets"}
    session, onb = _session(
        onb,
        asyncio.run(onb.next_step()),
        Scripted('{"acts":[{"type":"answer","field":"city","value_span":"Agra"}],"confidence":"high"}'),
    )
    asyncio.run(session.turn("Agra"))
    session.chat = Scripted('{"acts":[{"type":"change_request","field":"city"}],"confidence":"high"}')
    asyncio.run(session.turn("sorry, the city is Prayagraj, not Agra"))
    session.chat = Scripted(
        '{"acts":[{"type":"answer","field":"city","value_span":"the earlier one"}],"confidence":"high"}'
    )

    reply = asyncio.run(session.turn("the earlier one"))

    assert onb.answers["city"] == "Agra"
    assert "earlier" not in onb.answers["city"]
    assert "Agra" in reply.text


def test_a_history_phrase_is_not_saved_when_nothing_came_before() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Field Day Sporting"}
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"the first spelling"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("the first spelling"))

    assert onb.answers["shop_name"] == "Field Day Sporting"
    assert "earlier one" in reply.text


def test_a_shop_name_correction_stops_before_the_question() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Old Name Shop"}
    note = (
        '{"acts":[{"type":"correct","field":"shop_name",'
        '"value_span":"Ribbon Reel Gifts, why did you ask again"}],"confidence":"high"}'
    )
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    asyncio.run(session.turn("sorry, the shop name is Ribbon Reel Gifts, why did you ask again"))

    assert onb.answers["shop_name"] == "Ribbon Reel Gifts"
    assert "city" not in onb.answers


def test_yes_dhaba_is_stored_as_a_restaurant() -> None:
    onb = Shop()
    onb.order = ["business_type"]
    note = '{"acts":[{"type":"confirm_yes","field":"business_type","value_span":"dhaba"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))
    session.dialogue.awaiting = "confirm:business_type"
    session.dialogue.proposed = {"field": "business_type", "value": "dhaba"}

    reply = asyncio.run(session.turn("yes, dhaba"))

    assert onb.answers["business_type"] == "restaurant"
    assert "restaurant" in reply.text


def test_a_name_in_a_city_stays_whole_when_the_model_keeps_the_city() -> None:
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"Iron Yard Gym in Nashik"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))

    reply = asyncio.run(session.turn("Iron Yard Gym in Nashik"))

    assert onb.answers == {"shop_name": "Iron Yard Gym in Nashik"}
    assert "Got it, Iron Yard Gym in Nashik." in reply.text
    assert reply.step["pending"]["name"] == "city"


def test_a_name_in_a_city_saves_both_when_the_model_already_left_the_city_out() -> None:
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"Iron Yard Gym"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))

    reply = asyncio.run(session.turn("Iron Yard Gym in Nashik"))

    assert onb.answers == {"shop_name": "Iron Yard Gym", "city": "Nashik"}
    assert "Got it, Iron Yard Gym." in reply.text
    assert "Got it, Nashik." in reply.text
    assert reply.step["pending"]["name"] == "business_type"


def test_made_in_japan_stays_the_shop_name() -> None:
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"Made in Japan"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))

    asyncio.run(session.turn("Made in Japan"))

    assert onb.answers == {"shop_name": "Made in Japan"}


def test_a_city_and_its_shop_kind_are_both_saved() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Pallavi Cloth Hall"}
    note = '{"acts":[{"type":"answer","field":"city","value_span":"Surat, and it\'s a retail shop"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("Surat, and it's a retail shop"))

    assert onb.answers["city"] == "Surat"
    assert onb.answers["business_type"] == "retail"
    assert "Got it, Surat." in reply.text
    assert "Got it, retail." in reply.text


def test_made_in_india_stays_the_shop_name() -> None:
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"Made in India"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))

    asyncio.run(session.turn("Made in India"))

    assert onb.answers == {"shop_name": "Made in India"}


def test_a_wider_city_phrase_keeps_the_models_city() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Blue Anchor Dhaba"}
    note = '{"acts":[{"type":"answer","field":"city","value_span":"Pune"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    asyncio.run(session.turn("the city is where my brother lives, Pune"))

    assert onb.answers["city"] == "Pune"


def test_a_different_named_value_still_replaces_the_models_value() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Sarma Sweets"}
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"Sarma"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    asyncio.run(session.turn("sorry, the shop name is Sharma"))

    assert onb.answers["shop_name"] == "Sharma"


def test_a_sentence_with_in_is_not_split_into_a_city() -> None:
    note = '{"acts":[{"type":"answer","field":"shop_name","value_span":"we\'re based in Noida"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))

    reply = asyncio.run(session.turn("we're based in Noida"))

    assert onb.answers == {}
    assert "didn't catch" in reply.text.lower()
    assert reply.step["pending"]["name"] == "shop_name"


def test_no_on_the_phones_question_is_saved() -> None:
    onb = Shop()
    onb.order = ["stores_payer_phones"]
    note = '{"acts":[{"type":"confirm_no"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    reply = asyncio.run(session.turn("no"))

    assert onb.answers["stores_payer_phones"] == "No"
    assert "No" in reply.text


def test_yes_labeled_as_payments_fills_the_phones_question() -> None:
    onb = Shop()
    onb.order = ["stores_payer_phones"]
    onb.answers = {"payment_methods": "cash"}
    note = '{"acts":[{"type":"answer","field":"payment_methods","value_span":"yes"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    asyncio.run(session.turn("yes"))

    assert onb.answers["stores_payer_phones"] == "Yes"
    assert onb.answers["payment_methods"] == "cash"


def test_confirm_yes_with_nothing_proposed_is_not_silent() -> None:
    note = '{"acts":[{"type":"confirm_yes"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))

    reply = asyncio.run(session.turn("yes"))

    assert onb.answers == {}
    assert reply.text.strip()


def test_no_still_cancels_a_real_confirmation() -> None:
    note = '{"acts":[{"type":"confirm_no"}],"confidence":"high"}'
    session, onb = _session(chat=Scripted(note))
    session.dialogue.awaiting = "confirm:shop_name"
    session.dialogue.proposed = {"field": "shop_name", "value": "Nope Stores"}

    reply = asyncio.run(session.turn("no"))

    assert onb.answers == {}
    assert "leave that" in reply.text.lower()


def test_a_note_is_not_kept_for_recall_and_an_old_resume_still_loads() -> None:
    state = DialogueState()
    state.remember("monthly_volume", "120000")
    state.remember("note", "account 552100387716")
    assert state.values == {"monthly_volume": ["120000"]}
    restored = DialogueState.restore({"resume_to": "city", "values": {"city": ["Pune"]}, "recent": []})
    assert restored.values == {"city": ["Pune"]}
    assert not hasattr(restored, "resume_to")


def test_a_dead_model_does_not_save_a_city_sentence() -> None:
    class Mute(ChatModel):
        def complete(self, messages, max_tokens, schema=None):
            return None

    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Blue Anchor Dhaba"}
    session, onb = _session(onb, asyncio.run(onb.next_step()), Mute())

    reply = asyncio.run(session.turn("my brother's place"))

    assert onb.answers == {"shop_name": "Blue Anchor Dhaba"}
    assert "didn't catch" in reply.text.lower()
    assert reply.step["pending"]["name"] == "city"

    reply = asyncio.run(session.turn("Pune"))

    assert onb.answers["city"] == "Pune"


def test_a_dead_model_does_not_save_free_text() -> None:
    class Mute(ChatModel):
        def complete(self, messages, max_tokens, schema=None):
            return None

    session, onb = _session(chat=Mute())

    reply = asyncio.run(session.turn("ok thanks"))

    assert onb.answers == {}
    assert "didn't catch" in reply.text.lower()
    assert reply.step["pending"]["name"] == "shop_name"


def test_ok_is_not_greeted_as_hi() -> None:
    chat = Scripted('{"acts":[{"type":"chitchat"}],"confidence":"high"}')
    session, _onb = _session(chat=chat)

    reply = asyncio.run(session.turn("ok"))

    assert reply.text == "Great."
    assert "Hi!" not in reply.text


def test_a_why_keeps_the_value_we_were_waiting_for() -> None:
    onb = Shop()
    onb.index = 1
    onb.answers = {"shop_name": "Old Name"}
    session, onb = _session(
        onb,
        asyncio.run(onb.next_step()),
        Scripted('{"acts":[{"type":"change_request","field":"shop_name"}],"confidence":"high"}'),
    )
    first = asyncio.run(session.turn("can I change the shop name?"))
    assert "shop name" in first.text.lower()
    session.chat = Scripted('{"acts":[{"type":"why","field":"shop_name"}],"confidence":"high"}')
    asyncio.run(session.turn("why do you need it?"))
    assert session.dialogue.awaiting == "value_for:shop_name"
    session.chat = Scripted(
        '{"acts":[{"type":"answer","field":"city","value_span":"Sharma Sweets"}],"confidence":"high"}'
    )

    asyncio.run(session.turn("Sharma Sweets"))

    assert onb.answers["shop_name"] == "Sharma Sweets"


def test_the_phones_question_changes_after_two_misses() -> None:
    onb = Shop()
    onb.order = ["stores_payer_phones"]
    note = '{"acts":[{"type":"answer","field":"stores_payer_phones","value_span":"maybe"}],"confidence":"high"}'
    session, onb = _session(onb, asyncio.run(onb.next_step()), Scripted(note))

    asyncio.run(session.turn("maybe"))
    reply = asyncio.run(session.turn("maybe"))

    assert onb.answers == {}
    assert reply.prompt == "Just type yes or no."


def test_a_named_file_from_the_model_is_stored() -> None:
    onb = Shop()
    step = {
        "application_id": "app_1",
        "pending": {"kind": "upload", "name": "bank_proof"},
        "snapshot": {"answers": {}, "files": {}},
    }

    async def next_step(application_id=None):
        return step

    async def save_file(application_id, slot, file=None, missing=False):
        onb.calls.append(("save_file", slot, file, missing))
        return {"state": "accepted"}

    onb.next_step = next_step
    onb.save_file = save_file
    note = '{"acts":[{"type":"upload"}],"confidence":"high"}'
    session, onb = _session(onb, step, Scripted(note))

    reply = asyncio.run(session.turn("here's the bank letter bank-proof.pdf"))

    assert ("save_file", "bank_proof", "bank-proof.pdf", False) in onb.calls
    assert "accepted" in reply.text.lower()

"""An attached file is accepted whatever its name; the slot comes from the form, never the name."""

import asyncio

from copilot.session import Session
from test_session import FakeChat, FakeCorpus, FakeOnb

DATA = "data:application/pdf;base64,JVBERi0="

TWO_OPEN = {
    "application_id": "app",
    "pending": {"kind": "upload", "name": "bank_proof"},
    "snapshot": {
        "answers": {"shop_name": "Lotus Tea House"},
        "files": {"bank_proof": {"state": "missing"}, "owner_id": {"state": "missing"}},
    },
}

NOTHING_PENDING = {
    "application_id": "app",
    "pending": None,
    "snapshot": {
        "answers": {"shop_name": "Lotus Tea House"},
        "files": {"bank_proof": {"state": "missing"}, "owner_id": {"state": "missing"}},
    },
}


def _upload(step, name, document=None):
    onb = FakeOnb()
    chat = FakeChat()
    session = Session(chat, onb, FakeCorpus(), "app", step)
    reply = asyncio.run(session.turn(name, payload=DATA, document=document))
    return reply, onb, chat


def test_any_name_is_saved_to_the_document_the_form_names() -> None:
    for name in ["IMG_2024 (1).jpg", "scan.pdf", "my file final v2.png", "रसीद.pdf", "x.PDF"]:
        reply, onb, chat = _upload(TWO_OPEN, name, document="owner_id")
        assert reply.trace["action"] == "file", name
        assert ("save_file", "owner_id", DATA, False) in onb.calls, name
        assert chat.calls == 0, name


def test_without_a_document_the_pending_slot_is_used() -> None:
    reply, onb, _ = _upload(TWO_OPEN, "random name.jpg")
    assert reply.trace["action"] == "file"
    assert ("save_file", "bank_proof", DATA, False) in onb.calls


def test_a_name_with_slot_words_does_not_redirect_the_file() -> None:
    reply, onb, _ = _upload(TWO_OPEN, "owner id card.jpg", document="bank_proof")
    assert ("save_file", "bank_proof", DATA, False) in onb.calls


def test_no_document_and_no_pending_upload_asks_which() -> None:
    reply, onb, _ = _upload(NOTHING_PENDING, "photo.jpg")
    assert reply.trace["action"] == "which"
    assert not any(call[0] == "save_file" for call in onb.calls)

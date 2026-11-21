"""FE contract shape: ConversationView create + one message turn."""

import asyncio
import os
import sys
from contextlib import contextmanager
from threading import Event, Thread
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from copilot.app import create_app
from copilot.chat.recorded_chat import RecordedChat
from copilot.corpus.passages import Passages
from copilot.history import ConversationHistory, History
from copilot.identity import Merchant
from copilot.onb.onb_tools import OnbTools
from copilot.session import Session

APP_ID = "app_abcdef123456"


class EmptyCorpus(Passages):
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.document_ids: set[str] = set()

    def search(self, query, k=4):
        return []


class FakeOnb(OnbTools):
    def __init__(self) -> None:
        self.writes = 0
        self.step = {
            "application_id": APP_ID,
            "pending": {"kind": "field", "name": "shop_name"},
            "snapshot": {"answers": {}, "files": {}},
        }

    async def next_step(self, application_id=None):
        return self.step

    async def save_answer(self, application_id, field, value):
        self.writes += 1
        self.step = {
            "application_id": application_id,
            "pending": {"kind": "field", "name": "city"},
            "snapshot": {"answers": {field: value}, "files": {}},
        }
        return {"application_id": application_id, "field": field, "value": value}

    async def save_file(self, application_id, slot, file=None, missing=False):
        self.writes += 1
        self.step["snapshot"]["files"][slot] = {"filename": file}
        self.step["pending"] = {"kind": "upload", "name": "bank_proof"}
        return {"application_id": application_id}

    async def submit(self, application_id):
        return {}

    async def get_review(self, application_id):
        return {}


def factory(onb, session_cls=Session, chat=None):
    seen = []

    async def start(bearer: str, application_id: str | None):
        seen.append((bearer, application_id))
        step = await onb.next_step(application_id)
        return session_cls(chat or RecordedChat({}), onb, EmptyCorpus(), step["application_id"], step), step

    return start, seen


@pytest.fixture
def history():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set TEST_DATABASE_URL to run HTTP integration tests against PostgreSQL")
    name = f"copilot_test_{uuid4().hex}"
    schema = sql.Identifier(name)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        try:
            yield History(make_conninfo(dsn, options=f"-c search_path={name}"))
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))


def _verify(bearer):
    return {"test-token": Merchant("google:test"), "new-token": Merchant("google:test"),
            "other-token": Merchant("google:other")}.get(bearer)


@pytest.fixture
def open_client(history):
    @contextmanager
    def open_(start):
        backend_options = {"loop_factory": asyncio.SelectorEventLoop} if sys.platform == "win32" else {}
        with TestClient(create_app(start, History(history.dsn), _verify), backend_options=backend_options,
                        raise_server_exceptions=False) as client:
            yield client
    return open_


AUTH = {"Authorization": "Bearer test-token", "X-Merchant-Id": "google:test"}
ROOT = "/v1/conversations"


def test_health_and_one_turn(open_client) -> None:
    start, _ = factory(FakeOnb())
    with open_client(start) as client:
        _check_turn_contract(client)


def _check_turn_contract(client):
    assert client.get("/v1/health").json()["ok"] is True
    opened = client.post("/v1/conversations", headers=AUTH)
    assert opened.status_code == 201
    body = opened.json()
    conv = body["conversation"]
    assert conv["id"] == APP_ID
    assert conv["prompt"]["field"] == "shop_name"
    assert conv["prompt"]["pills"] == []
    assert len(conv["messages"]) == 2
    assert "Welcome to iPe" in conv["messages"][0]["text"]
    assert "shop" in conv["messages"][1]["text"].lower()
    turned = client.post(
        f"/v1/conversations/{conv['id']}/messages",
        headers=AUTH,
        json={"text": "Lotus Tea House"},
    )
    assert turned.status_code == 200
    out = turned.json()["conversation"]
    assert out["prompt"]["field"] == "city"
    assert out["shop_name"] == "Lotus Tea House"
    loaded = client.get(f"/v1/conversations/{conv['id']}", headers=AUTH)
    assert loaded.status_code == 200
    assert len(loaded.json()["conversation"]["messages"]) >= 2
    listed = client.get("/v1/conversations", headers=AUTH)
    assert listed.status_code == 200
    assert listed.json()["conversations"][0]["id"] == APP_ID


def test_restart_restores_correction_and_uses_latest_onb_snapshot(open_client) -> None:
    class CorrectionChat:
        def complete(self, messages, max_tokens, schema=None):
            if "confirm:shop_name" in str(messages):
                return '{"acts":[{"type":"confirm_yes"}],"confidence":"high"}'
            return '{"acts":[{"type":"confirm","field":"shop_name","value_span":"Lotus Teas"}],"confidence":"high"}'

    onb = FakeOnb()
    start, seen = factory(onb, chat=CorrectionChat())
    path = f"{ROOT}/{APP_ID}"
    with open_client(start) as client:
        assert client.post(ROOT, headers=AUTH).status_code == 201
        response = client.post(f"{path}/messages", headers=AUTH, json={
            "text": "Lotus Tea House",
        })
        assert response.status_code == 200, response.text
        assert onb.step["snapshot"]["answers"]["shop_name"] == "Lotus Tea House"
        response = client.post(f"{path}/messages", headers=AUTH, json={
            "text": "Is the shop name Lotus Teas?", "client_message_id": "correction",
        })
        assert response.status_code == 200, response.text
        saved = response.json()["conversation"]
        assert saved["prompt"]["field"] == "shop_name"
        assert any("Did you mean Lotus Teas" in m["text"] for m in saved["messages"])

    onb.step["snapshot"]["answers"]["shop_name"] = "Latest ONB name"
    refreshed = {"Authorization": "Bearer new-token"}
    with open_client(start) as client:
        response = client.post(ROOT, headers=refreshed, json={"application_id": APP_ID})
        assert response.status_code == 200, response.text
        restored = response.json()["conversation"]
        assert restored["messages"] == saved["messages"]
        assert restored["prompt"] == saved["prompt"]
        assert restored["shop_name"] == "Latest ONB name"
        assert seen[-1] == ("new-token", APP_ID)
        response = client.post(f"{path}/messages", headers=refreshed, json={"text": "yes"})
        assert response.status_code == 200, response.text
        assert onb.step["snapshot"]["answers"]["shop_name"] == "Lotus Teas"
        assert response.json()["conversation"]["prompt"]["field"] == "city"


def test_missing_bearer_is_401(open_client) -> None:
    start, _ = factory(FakeOnb())
    with open_client(start) as client:
        r = client.post(ROOT, headers={"X-Merchant-Id": "google:test"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_onb_invalid_token_is_401(open_client) -> None:
    async def boom(_bearer: str, _application_id: str | None):
        raise RuntimeError("invalid_token: ONB rejected the Google access token")

    with open_client(boom) as client:
        r = client.post(ROOT, headers=AUTH)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_onb_generic_mcp_4xx_is_401(open_client) -> None:
    async def boom(_bearer: str, _application_id: str | None):
        raise RuntimeError("Server returned an error response")

    with open_client(boom) as client:
        r = client.post(ROOT, headers=AUTH)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_corpus_failure_is_corpus_unavailable(open_client) -> None:
    class BoomSession(Session):
        async def turn(self, line: str):
            raise RuntimeError("corpus POST /v1/search failed HTTP 502: <html>")

    start, _ = factory(FakeOnb(), session_cls=BoomSession)
    with open_client(start) as client:
        opened = client.post(ROOT, headers=AUTH)
        cid = opened.json()["conversation"]["id"]
        r = client.post(f"{ROOT}/{cid}/messages", headers=AUTH, json={"text": "Why?"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "corpus_unavailable"


def test_only_authenticated_owner_can_access_or_claim_history(open_client):
    start, seen = factory(FakeOnb())
    path = f"{ROOT}/{APP_ID}"
    with open_client(start) as client:
        assert client.post(ROOT, headers=AUTH).status_code == 201
        other = {"Authorization": "Bearer other-token", "X-Merchant-Id": "google:other"}
        spoofed = dict(other, **{"X-Merchant-Id": "google:test"})
        assert client.get(path, headers=spoofed).status_code == 401
        assert client.get(path, headers=other).status_code == 404
        assert client.get(ROOT, headers=other).json() == {"conversations": []}
        assert client.post(f"{path}/messages", headers=other, json={"text": "hi"}).status_code == 404
        assert client.post(f"{path}/files", headers=other, files={"file": ("file.pdf", b"pdf")}).status_code == 404
        assert client.post(ROOT, headers=other, json={"application_id": APP_ID}).status_code == 404
        assert client.post(ROOT, headers=AUTH, json={"application_id": "app_unclaimed"}).status_code == 404
        assert seen == [("test-token", None)]


def test_retries_after_commit_or_interruption_do_not_replay_onb(open_client, monkeypatch):
    onb = FakeOnb()
    start, _ = factory(onb)
    path = f"{ROOT}/{APP_ID}/messages"
    payload = {"text": "Lotus Tea House", "client_message_id": "stable-id"}
    with open_client(start) as client:
        assert client.post(ROOT, headers=AUTH).status_code == 201
        original_save = ConversationHistory.save

        async def fail_before_commit(record, view, dialogue):
            assert onb.writes == 1
            await original_save(record, view, dialogue)
            raise RuntimeError("interrupted before commit")

        monkeypatch.setattr(ConversationHistory, "save", fail_before_commit)
        assert client.post(path, headers=AUTH, json=payload).status_code == 500
        assert onb.writes == 1

    monkeypatch.setattr(ConversationHistory, "save", original_save)
    with open_client(start) as client:
        recovered = client.post(path, headers=AUTH, json=payload)
        assert recovered.status_code == 200, recovered.text
        view = recovered.json()["conversation"]
        assert view["prompt"]["field"] == "city"
        assert sum(m["role"] == "merchant" for m in view["messages"]) == 1
        assert sum("did not resend" in m["text"] for m in view["messages"]) == 1
        retry = client.post(path, headers=AUTH, json=payload)
        assert retry.json() == recovered.json()
        assert client.post(path, headers=AUTH, json=dict(payload, text="Different")).status_code == 409
        assert onb.writes == 1


def test_concurrent_retries_across_instances_use_one_turn(open_client):
    entered, release = Event(), Event()

    class SlowSession(Session):
        async def turn(self, line):
            entered.set()
            assert await asyncio.to_thread(release.wait, 10)
            return await super().turn(line)

    onb = FakeOnb()
    start, _ = factory(onb, session_cls=SlowSession)
    path = f"{ROOT}/{APP_ID}/messages"
    payload = {"text": "Lotus Tea House", "client_message_id": "same-turn"}
    with open_client(start) as first, open_client(start) as second:
        assert first.post(ROOT, headers=AUTH).status_code == 201
        results = []
        worker = Thread(target=lambda: results.append(first.post(path, headers=AUTH, json=payload)))
        worker.start()
        try:
            assert entered.wait(10)
            busy = second.post(path, headers=AUTH, json=payload)
            assert busy.status_code == 409
            assert busy.json()["error"]["code"] == "conversation_busy"
        finally:
            release.set()
            worker.join(10)
        assert results[0].status_code == 200
        assert second.post(path, headers=AUTH, json=payload).json() == results[0].json()
        assert onb.writes == 1


def test_upload_retry_persists_attachment_once(open_client):
    onb = FakeOnb()
    onb.step["pending"] = {"kind": "upload", "name": "owner_id"}
    start, _ = factory(onb)
    path = f"{ROOT}/{APP_ID}/files"
    payload = {"data": {"client_message_id": "upload", "document": "owner_id"},
               "files": {"file": ("owner.pdf", b"pdf")}}
    with open_client(start) as client:
        assert client.post(ROOT, headers=AUTH).status_code == 201
        sent = client.post(path, headers=AUTH, **payload)
        assert sent.status_code == 200, sent.text
    with open_client(start) as client:
        retry = client.post(path, headers=AUTH, **payload)
        assert retry.json() == sent.json()
    assert onb.writes == 1
    messages = [m for m in sent.json()["conversation"]["messages"] if m["role"] == "merchant"]
    assert [m["attachments"] for m in messages] == [[{"document": "owner_id", "filename": "owner.pdf"}]]

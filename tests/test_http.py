"""FE contract shape: ConversationView create + one message turn."""

from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.chat.recorded_chat import RecordedChat
from copilot.corpus.passages import Passages
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
        self.step = {
            "application_id": APP_ID,
            "pending": {"kind": "field", "name": "shop_name"},
            "snapshot": {"answers": {}, "files": {}},
        }

    async def next_step(self, application_id=None):
        return self.step

    async def save_answer(self, application_id, field, value):
        self.step = {
            "application_id": application_id,
            "pending": {"kind": "field", "name": "city"},
            "snapshot": {"answers": {field: value}, "files": {}},
        }
        return {"application_id": application_id, "field": field, "value": value}

    async def save_file(self, application_id, slot, file=None, missing=False):
        return {}

    async def submit(self, application_id):
        return {}

    async def get_review(self, application_id):
        return {}


async def _start(bearer: str):
    assert bearer
    onb = FakeOnb()
    step = await onb.next_step()
    session = Session(RecordedChat({}), onb, EmptyCorpus(), step["application_id"], step)
    return session, step


AUTH = {"Authorization": "Bearer test-token", "X-Merchant-Id": "google:test"}


def test_health_and_one_turn() -> None:
    client = TestClient(create_app(_start))
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


def test_resume_sends_the_application_id() -> None:
    seen: dict[str, str | None] = {}

    async def _resume(bearer: str, application_id: str | None = None):
        assert bearer
        seen["id"] = application_id
        onb = FakeOnb()
        onb.step = {
            "application_id": application_id or APP_ID,
            "pending": {"kind": "field", "name": "city"},
            "snapshot": {"answers": {"shop_name": "Lotus Tea House"}, "files": {}},
        }
        step = await onb.next_step(application_id)
        session = Session(RecordedChat({}), onb, EmptyCorpus(), step["application_id"], step)
        return session, step

    client = TestClient(create_app(_resume))
    opened = client.post(
        "/v1/conversations",
        headers=AUTH,
        json={"application_id": "app_resume01"},
    )
    assert opened.status_code == 201
    assert seen["id"] == "app_resume01"
    conv = opened.json()["conversation"]
    assert conv["id"] == "app_resume01"
    assert conv["messages"][0]["text"].startswith("Welcome back")
    assert "Lotus Tea House" in conv["messages"][0]["text"]
    assert "city" in conv["messages"][1]["text"].lower()
    again = client.post(
        "/v1/conversations",
        headers=AUTH,
        json={"application_id": "app_resume01"},
    )
    assert again.status_code == 200
    assert again.json()["conversation"]["id"] == "app_resume01"


def test_missing_bearer_is_401() -> None:
    client = TestClient(create_app(_start))
    r = client.post("/v1/conversations", headers={"X-Merchant-Id": "google:test"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_onb_invalid_token_is_401() -> None:
    async def boom(_bearer: str):
        raise RuntimeError("invalid_token: ONB rejected the Google access token")

    client = TestClient(create_app(boom))
    r = client.post("/v1/conversations", headers=AUTH)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_onb_generic_mcp_4xx_is_401() -> None:
    async def boom(_bearer: str):
        raise RuntimeError("Server returned an error response")

    client = TestClient(create_app(boom))
    r = client.post("/v1/conversations", headers=AUTH)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_corpus_failure_is_corpus_unavailable() -> None:
    from copilot.session import Session

    class BoomSession(Session):
        async def turn(self, line: str):
            raise RuntimeError("corpus POST /v1/search failed HTTP 502: <html>")

    async def start(bearer: str):
        session, step = await _start(bearer)
        return BoomSession(session.chat, session.onb, session.corpus, session.application_id, step), step

    client = TestClient(create_app(start))
    opened = client.post("/v1/conversations", headers=AUTH)
    cid = opened.json()["conversation"]["id"]
    r = client.post(f"/v1/conversations/{cid}/messages", headers=AUTH, json={"text": "Why?"})
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "corpus_unavailable"

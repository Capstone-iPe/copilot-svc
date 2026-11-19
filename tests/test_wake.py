"""A sleeping ONB or corpus answers with HTML or drops the connection. Retry those."""

from __future__ import annotations

import asyncio

import pytest

from copilot.app import _onb_http_error
from copilot.corpus.remote import RemoteCorpus
from copilot.onb.mcp_onb import LiveOnb, OnbAsleep


class _Payload:
    structuredContent = {"application_id": "app_1", "pending": {"name": "shop_name"}}


class _Client:
    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def call_tool(self, name, arguments):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise TimeoutError("timed out")
        return _Payload()

    async def __aexit__(self, *args):
        return None


class _Http:
    async def aclose(self):
        return None

    async def post(self, *args, **kwargs):
        class _Response:
            status_code = 502

        return _Response()


def test_a_sleeping_onb_is_retried_until_it_answers(monkeypatch) -> None:
    opened = {"n": 0}

    async def connect(url, bearer_fn):
        opened["n"] += 1
        if opened["n"] < 3:
            raise OnbAsleep(502)
        return _Client(), _Http()

    async def sleep(_delay):
        return None

    monkeypatch.setattr("copilot.onb.mcp_onb.connect_bearer", connect)
    monkeypatch.setattr("copilot.onb.mcp_onb.asyncio.sleep", sleep)
    onb = LiveOnb("https://onb.example/mcp", lambda: "token")

    step = asyncio.run(onb.next_step())

    assert opened["n"] == 3
    assert step["application_id"] == "app_1"


def test_a_rejected_token_is_not_retried(monkeypatch) -> None:
    opened = {"n": 0}

    async def connect(url, bearer_fn):
        opened["n"] += 1
        raise RuntimeError("invalid_token: ONB rejected the Google access token")

    monkeypatch.setattr("copilot.onb.mcp_onb.connect_bearer", connect)
    onb = LiveOnb("https://onb.example/mcp", lambda: "token")

    with pytest.raises(RuntimeError, match="invalid_token"):
        asyncio.run(onb.next_step())
    assert opened["n"] == 1


def test_a_dropped_tool_call_is_retried(monkeypatch) -> None:
    opened = {"n": 0}

    async def connect(url, bearer_fn):
        opened["n"] += 1
        return _Client(fail_times=1 if opened["n"] == 1 else 0), _Http()

    async def sleep(_delay):
        return None

    monkeypatch.setattr("copilot.onb.mcp_onb.connect_bearer", connect)
    monkeypatch.setattr("copilot.onb.mcp_onb.asyncio.sleep", sleep)
    onb = LiveOnb("https://onb.example/mcp", lambda: "token")

    step = asyncio.run(onb.next_step())

    assert step["pending"]["name"] == "shop_name"


def test_onb_still_asleep_is_not_a_sign_in_error() -> None:
    error = _onb_http_error(OnbAsleep(502), opening=True)
    assert error.status_code == 503
    assert error.detail["code"] == "onb_unavailable"
    assert "waking" in error.detail["message"]


class _Json:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        import json

        return json.dumps(self._payload).encode()


def test_corpus_timeout_is_retried(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_urlopen(request, timeout=10):
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("timed out")
        return _Json({"hits": [{"document_id": "ONB-POL-001", "text": "x", "folder": "policy"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("copilot.corpus.remote.time.sleep", lambda _s: None)
    hits = RemoteCorpus("http://corpus.test", "secret-key").search("why")
    assert calls["n"] == 2
    assert hits[0]["document_id"] == "ONB-POL-001"


def test_corpus_html_page_is_retried(monkeypatch) -> None:
    calls = {"n": 0}

    class _Html:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"<html>waking</html>"

    def fake_urlopen(request, timeout=10):
        calls["n"] += 1
        if calls["n"] < 2:
            return _Html()
        return _Json({"document_ids": ["ONB-POL-001"]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("copilot.corpus.remote.time.sleep", lambda _s: None)
    assert RemoteCorpus("http://corpus.test", "secret-key").document_ids == {"ONB-POL-001"}
    assert calls["n"] == 2

"""RemoteCorpus talks to onb-corpus with a Bearer token."""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from copilot.corpus.remote import RemoteCorpus


class _Resp:
    def __init__(self, payload: dict, code: int = 200) -> None:
        self._payload = payload
        self.status = code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def test_search_sends_bearer(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=60):
        seen["url"] = request.full_url
        seen["auth"] = request.headers.get("Authorization")
        body = json.loads(request.data.decode())
        seen["body"] = body
        return _Resp(
            {
                "hits": [
                    {
                        "document_id": "ONB-POL-001",
                        "path": "documents/policy/ONB-POL-001.md",
                        "folder": "policy",
                        "text": "bank proof",
                        "search_text": "ONB-POL-001\nbank proof",
                        "in_force": True,
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    corpus = RemoteCorpus("http://corpus.test", "secret-key")
    hits = corpus.search("why bank proof", k=4)
    assert seen["url"] == "http://corpus.test/v1/search"
    assert seen["auth"] == "Bearer secret-key"
    assert seen["body"] == {"query": "why bank proof", "k": 4}
    assert hits[0]["document_id"] == "ONB-POL-001"


def test_document_ids(monkeypatch):
    def fake_urlopen(request, timeout=60):
        assert request.full_url.endswith("/v1/document-ids")
        assert request.headers.get("Authorization") == "Bearer secret-key"
        return _Resp({"document_ids": ["ONB-POL-001", "ONB-ANX-001"]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    corpus = RemoteCorpus("http://corpus.test", "secret-key")
    assert corpus.document_ids == {"ONB-POL-001", "ONB-ANX-001"}


def test_http_401(monkeypatch):
    def fake_urlopen(request, timeout=60):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", hdrs=None, fp=BytesIO(b"invalid")
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    corpus = RemoteCorpus("http://corpus.test", "bad")
    with pytest.raises(RuntimeError, match="401"):
        corpus.search("why")

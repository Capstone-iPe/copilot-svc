import asyncio
import io
import json

import httpx
import pytest

from copilot.chat import qwen_chat
from copilot.explain.why import why_reply
from copilot.history import TraceDeliveryError
from copilot.intent.classifier import classify
from copilot.observability import LangfuseDelivery, Settings, complete_model, retrieve, turn_capture, utcnow


def settings(content=False):
    return Settings("pk-lf-fake", "sk-lf-fake", "http://127.0.0.1:3000", "test-pseudonym-key",
                    "test", "123abc", content)


@pytest.mark.parametrize("content", [False, True])
def test_model_and_retrieval_observations_follow_content_setting(monkeypatch, content):
    monkeypatch.setenv("CHAT_API_KEY", "even-unlabelled-chat-credential")
    monkeypatch.setenv("CHAT_MODEL", "actual/model")
    model = qwen_chat.QwenChat()
    answers = iter([
        {"choices": [{"message": {"content": '{"intent":"ask"}'}}],
         "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}},
        {"choices": [{"message": {"content": "Bearer raw-token even-unlabelled-chat-credential"}}]},
        {"choices": [{"message": {"content": "a policy completion"}}]},
    ])
    monkeypatch.setattr(qwen_chat, "_ssl_context", lambda: None)
    monkeypatch.setattr(qwen_chat.urllib.request, "urlopen",
                        lambda *args, **kwargs: io.BytesIO(json.dumps(next(answers)).encode()))

    class Corpus:
        def __init__(self):
            self.document_ids = {"FAQ-001", "FAQ-002"}
            self.rows = []

        def search(self, query, k):
            return [{"document_id": "FAQ-001" if query.startswith("why ") else "FAQ-002",
                     "chunk_id": "chunk-1234", "folder": "faq", "score": 0.5,
                     "text": "private policy text; merchant@example.test"}]

    question = "Tell me about account 123456"
    with turn_capture(settings(content), "request-auth-secret", "merchant-identifier",
                      {"kind": "message", "line": question}) as capture:
        assert capture is not None
        classify(question, None, False, model.complete)
        why_reply(question, {"name": "shop_name"}, Corpus(), model.complete, mode="free")
        payload = capture.payload("app-123", "client:key", utcnow(), "success",
                                  output=["Visible reply 123456 request-auth-secret"])

    root, *operations = payload["events"]
    children = [op["body"] for op in operations]
    assert all(child["traceId"] == payload["trace_id"] and child["metadata"]["latency_ms"] >= 0
               for child in children)
    generations = [op["body"] for op in operations if op["type"] == "generation-create"]
    assert [op["name"] for op in generations] == ["intent-classification", "policy-explanation"]
    assert {op["model"] for op in generations} == {"actual/model"}
    assert len({op["metadata"]["template_version"] for op in generations}) == 2
    assert generations[0]["usageDetails"] == {"input": 10, "output": 2, "total": 12}
    assert generations[1]["metadata"]["usage"] == "unavailable"
    assert "usageDetails" not in generations[1]
    spans = [op["body"] for op in operations if op["type"] == "span-create"]
    assert len(spans) == 2
    assert spans[1]["metadata"]["hits"][0] == {
        "document_id": "FAQ-002", "chunk_id": "chunk-1234", "rank": 1, "score": 0.5,
        **({"text": "private policy text; [email hidden]"} if content else {}),
    }
    encoded = json.dumps(payload)
    assert all(secret not in encoded for secret in ("raw-token", "request-auth-secret", "123456", "merchant-identifier",
                                                     "merchant@example.test", "even-unlabelled-chat-credential"))
    assert ("output" in root["body"]) is content
    assert ("input" in generations[0] and "output" in generations[1] and "input" in spans[1]) is content


def test_sdk_delivery_checks_all_acknowledgements(monkeypatch):
    original = httpx.AsyncClient
    requests = []

    def endpoint(request):
        assert request.url.path == "/api/public/otel/v1/traces"
        assert request.headers["x-langfuse-ingestion-version"] == "4"
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(503, json={"message": "unavailable"})
        return httpx.Response(200, json={})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(endpoint),
                                                                       **kwargs))

    sent = {}

    async def run():
        config = settings()
        delivery = LangfuseDelivery(config)
        try:
            with turn_capture(config, "bearer", "owner", {"kind": "message", "line": ""}) as capture:
                assert capture is not None
                complete_model("generation", lambda *args: None, [], 1, None)
                retrieve(lambda query, k: [], "private query", k=3)
                sent["payload"] = capture.payload("app", "client:key", utcnow(), "success")
            with pytest.raises(TraceDeliveryError, match="http_503"):
                await delivery.send(sent["payload"])
            await delivery.send(sent["payload"])
        finally:
            await delivery.close()

    asyncio.run(run())
    assert requests[0] == requests[1]
    spans = requests[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert [span["name"] for span in spans] == ["copilot.message", "generation", "policy-retrieval"]
    assert spans[0]["traceId"] == sent["payload"]["trace_id"]
    assert {span["parentSpanId"] for span in spans[1:]} == {spans[0]["spanId"]}


def test_enabled_configuration_requires_project_keys(monkeypatch):
    monkeypatch.setenv("COPILOT_LANGFUSE_ENABLED", "false")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert Settings.load("0.1.0") is None
    monkeypatch.setenv("COPILOT_LANGFUSE_ENABLED", "true")
    with pytest.raises(RuntimeError, match="LANGFUSE_PUBLIC_KEY"):
        Settings.load("0.1.0")

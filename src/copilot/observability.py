"""Request-local capture and acknowledged Langfuse export from the durable outbox."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import re
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from urllib.parse import urlsplit

import httpx
from psycopg import Error as DatabaseError

from copilot.config import chat_api_key, corpus_api_key
from copilot.history import History, TraceDeliveryError
from copilot.words import DIGITS

log = logging.getLogger("copilot.telemetry")
_active: ContextVar[TurnTrace | None] = ContextVar("turn_trace", default=None)
_generation: ContextVar[dict | None] = ContextVar("generation", default=None)
_CREDENTIAL = re.compile(
    r"(?i)\bbearer\s+[^\s\"'\\,;]+|"
    r"\beyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+\b|"
    r"\b(?:sk|pk|sk-lf|pk-lf)-[a-z0-9_-]{8,}|"
    r"\b(?:api[_ -]?key|access[_ -]?token|password|secret|authorization)[\"']?\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)|"
    r"\b[a-z][a-z0-9+.-]*://[^/\s@]+:[^/\s@]+@"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}")


def _digest(*values: str) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()[:32]


def _flag(name: str) -> bool:
    value = os.getenv(name, "false").strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise RuntimeError(f"{name} must be true or false")
    return value in {"true", "1"}


@dataclass(frozen=True)
class Settings:
    public_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    base_url: str
    pseudonym_key: str = field(repr=False)
    environment: str
    release: str
    content: bool

    @property
    def destination(self) -> str:
        return _digest(self.base_url, self.public_key)

    @classmethod
    def load(cls, version: str) -> Settings | None:
        if not _flag("COPILOT_LANGFUSE_ENABLED"):
            return None
        public, secret, pseudonym = (
            os.getenv(name, "").strip()
            for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "COPILOT_TRACE_PSEUDONYM_KEY")
        )
        if not re.fullmatch(r"pk-lf-[\w-]+", public) or not re.fullmatch(r"sk-lf-[\w-]+", secret):
            raise RuntimeError("Set Langfuse project keys in LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY")
        if len(pseudonym) < 32:
            raise RuntimeError("Set COPILOT_TRACE_PSEUDONYM_KEY to a random secret of at least 32 characters")
        base = (os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST") or "").strip().rstrip("/")
        try:
            url = urlsplit(base)
            valid = (url.scheme == "https" or
                     (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}))
            valid = valid and bool(url.hostname) and (url.port is None or 0 < url.port <= 65535)
            valid = valid and not (url.username or url.password or url.query or url.fragment or re.search(r"\s", base))
        except ValueError:
            valid = False
        if not valid:
            raise RuntimeError("Set LANGFUSE_BASE_URL to an HTTPS instance URL (HTTP is allowed on loopback only)")
        environment = os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "development").strip()
        release = os.getenv("LANGFUSE_RELEASE", version).strip()
        if (not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", environment)
                or environment.startswith("langfuse")
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,99}", release)):
            raise RuntimeError("Invalid LANGFUSE_TRACING_ENVIRONMENT or LANGFUSE_RELEASE")
        return cls(public, secret, base, pseudonym, environment, release, _flag("COPILOT_TRACE_CAPTURE_CONTENT"))


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class TurnTrace:
    def __init__(self, settings: Settings, bearer: str, owner: str, request: dict):
        self.settings = settings
        self.kind = "submit" if request.get("action") == "submit" else request["kind"]
        self.user_id = hmac.new(settings.pseudonym_key.encode(), owner.encode(), hashlib.sha256).hexdigest()
        self.model: str | None = None
        self.operations: list[dict] = []
        self.fallbacks: set[str] = set()
        secrets = {
            bearer, owner, chat_api_key(), corpus_api_key(), settings.public_key, settings.secret_key,
            settings.pseudonym_key, os.getenv("DATABASE_URL"), request["line"] if self.kind == "file" else None,
        }
        self.secrets = sorted({
            form for secret in secrets if secret
            for form in (secret, json.dumps(secret, ensure_ascii=False)[1:-1], json.dumps(secret)[1:-1])
        }, key=len, reverse=True)

    def clean(self, text: str, limit: int = 8000, *, digits: bool = True) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        text = _EMAIL.sub("[email hidden]", _CREDENTIAL.sub("[credential hidden]", text))
        if digits:
            text = DIGITS.sub("[number hidden]", text)
        return text[:limit].replace("\x00", "")

    @contextmanager
    def activate(self) -> Generator[None]:
        token = _active.set(self)
        try:
            yield
        finally:
            _active.reset(token)

    def payload(self, cid: str, key: str, started: str, status: str, *, latency: float | None = None,
                decision: dict | None = None, output: list[str] | None = None,
                diagnostic: str | None = None) -> dict:
        trace_id = _digest("copilot-svc", cid, key)
        revision = 0 if status == "error" else 1
        ended = utcnow()
        metadata = {
            "status": status, "latency_ms": latency, "reply_trace": {
                field: self.clean(value, 128, digits=False) if isinstance(value, str) else value
                for field, value in (decision or {}).items()
            },
            "model": self.model, "fallbacks": sorted(self.fallbacks),
        }
        if diagnostic is not None:
            metadata["diagnostic"] = diagnostic
        if status == "interrupted/recovered":
            metadata["diagnostic"] = "reconciled_without_replay"
            metadata["completed_generation_trace"] = False
        root = {
            "id": trace_id, "sessionId": cid, "userId": self.user_id, "timestamp": started,
            "environment": self.settings.environment, "release": self.settings.release,
            "name": f"copilot.{self.kind}", "metadata": metadata,
        }
        if self.settings.content and output is not None:
            root["output"] = [self.clean(text) for text in output]
        events = [{"id": _digest(trace_id, str(revision), "root"), "type": "trace-create",
                   "timestamp": ended, "body": root}]
        for index, operation in enumerate(self.operations):
            body = {**operation, "id": _digest(trace_id, "operation", str(index)), "traceId": trace_id,
                    "environment": self.settings.environment}
            generation = "model" in body
            events.append({
                "id": _digest(trace_id, str(revision), str(index)), "timestamp": ended,
                "type": "generation-create" if generation else "span-create", "body": body,
            })
        return {"destination": self.settings.destination, "trace_id": trace_id,
                "revision": revision, "events": events}


def note_fallback(reason: str) -> None:
    if trace := _active.get():
        trace.fallbacks.add(reason)


def note_provider(model: str, usage: dict | None) -> None:
    operation = _generation.get()
    trace = _active.get()
    if operation is None or trace is None:
        return
    trace.model = operation["model"] = trace.clean(model, 128, digits=False)
    tokens = {
        name: count for provider, name in (
            ("prompt_tokens", "input"), ("completion_tokens", "output"), ("total_tokens", "total"),
        )
        if usage and type(count := usage.get(provider)) is int and count >= 0
    }
    if tokens:
        operation["usageDetails"] = tokens
        operation["metadata"]["usage"] = "provider_reported"


@contextmanager
def _operation(trace: TurnTrace, name: str) -> Generator[dict]:
    started = perf_counter()
    body = {"name": name, "startTime": utcnow(), "metadata": {}}
    trace.operations.append(body)
    try:
        yield body
    except Exception:
        body.update(level="ERROR", statusMessage="operation_failed")
        raise
    finally:
        body["endTime"] = utcnow()
        body["metadata"]["latency_ms"] = round((perf_counter() - started) * 1000, 2)


def complete_model(purpose: str, complete: Callable[..., str | None], messages: list[dict],
                   max_tokens: int, schema: dict | None) -> str | None:
    trace = _active.get()
    if trace is None:
        return complete(messages, max_tokens, schema)
    with _operation(trace, purpose) as body:
        body["model"] = None
        template = json.dumps([messages[:-1], schema], sort_keys=True, ensure_ascii=True)
        body["metadata"].update(template=purpose, template_version=_digest(template), usage="unavailable")
        if trace.settings.content:
            body["input"] = [{"role": m["role"], "content": trace.clean(m["content"])} for m in messages]
        token = _generation.set(body)
        try:
            result = complete(messages, max_tokens, schema)
        finally:
            _generation.reset(token)
        if not result:
            body.update(level="WARNING", statusMessage="completion_unavailable")
        elif trace.settings.content:
            body["output"] = trace.clean(result)
        return result


def retrieve(search: Callable[..., list[dict]], query: str, k: int) -> list[dict]:
    trace = _active.get()
    if trace is None:
        return search(query, k=k)
    with _operation(trace, "policy-retrieval") as body:
        if trace.settings.content:
            body["input"] = trace.clean(query)
        hits = search(query, k=k)
        rows = []
        for rank, hit in enumerate(hits[:k], 1):
            if not isinstance(hit, dict):
                continue
            row: dict = {"rank": rank}
            for name in ("document_id", "chunk_id", "id"):
                if isinstance(value := hit.get(name), (str, int)):
                    row[name] = trace.clean(str(value), 160, digits=False)
            if type(score := hit.get("score")) in {float, int} and math.isfinite(score):
                row["score"] = score
            if trace.settings.content and isinstance(text := hit.get("search_text") or hit.get("text"), str):
                row["text"] = trace.clean(text, 2000)
            rows.append(row)
        body["metadata"].update(hits=rows, requested_k=k)
        return hits


@contextmanager
def turn_capture(settings: Settings | None, bearer: str, owner: str,
                 request: dict) -> Generator[TurnTrace | None]:
    if settings is None:
        yield None
        return
    trace = TurnTrace(settings, bearer, owner, request)
    with trace.activate():
        yield trace


class LangfuseDelivery:
    def __init__(self, settings: Settings):
        from langfuse.api.client import AsyncFernLangfuse

        self.settings = settings
        self.transport = httpx.AsyncClient(timeout=5)
        self.api = AsyncFernLangfuse(
            base_url=settings.base_url, username=settings.public_key, password=settings.secret_key,
            x_langfuse_public_key=settings.public_key, httpx_client=self.transport,
        )

    async def check_config(self) -> None:
        from langfuse.api.core.api_error import ApiError

        try:
            async with asyncio.timeout(6):
                await self.api.projects.get(request_options={"max_retries": 0})
        except ApiError as exc:
            if exc.status_code in {400, 401, 403, 404, 405}:
                raise RuntimeError("Langfuse rejected project credentials or instance URL") from None
            log.warning("Langfuse startup check returned HTTP %s; outbox will retry", exc.status_code)
        except (httpx.RequestError, TimeoutError) as exc:
            log.warning("Langfuse startup check unavailable (%s); outbox will retry", type(exc).__name__)
        except ValueError:
            raise RuntimeError("LANGFUSE_BASE_URL did not return a Langfuse project response") from None

    async def send(self, payload: dict) -> None:
        """Post one stored turn to the OTLP trace endpoint that replaced /api/public/ingestion."""
        token = base64.b64encode(f"{self.settings.public_key}:{self.settings.secret_key}".encode()).decode()
        try:
            async with asyncio.timeout(10):
                response = await self.transport.post(
                    f"{self.settings.base_url}/api/public/otel/v1/traces",
                    json=_otel_request(payload),
                    headers={
                        "Authorization": f"Basic {token}",
                        "x-langfuse-ingestion-version": "4",
                    },
                )
        except (httpx.RequestError, TimeoutError, ValueError) as exc:
            raise TraceDeliveryError(type(exc).__name__) from None
        if response.status_code < 200 or response.status_code >= 300:
            raise TraceDeliveryError(f"http_{response.status_code}")

    async def close(self) -> None:
        await self.transport.aclose()


def _otel_request(payload: dict) -> dict:
    events = payload["events"]
    root = next(event for event in events if event["type"] == "trace-create")
    body = root["body"]
    trace_id = str(body["id"])
    parent = root["id"][:16]
    shared = _shared_attributes(body)
    spans = [_otel_span(root, trace_id, None, shared)]
    spans.extend(_otel_span(event, trace_id, parent, shared) for event in events if event is not root)
    return {"resourceSpans": [{
        "resource": {"attributes": [_otel_value("service.name", "copilot-svc")]},
        "scopeSpans": [{"scope": {"name": "copilot-svc"}, "spans": spans}],
    }]}


def _otel_span(event: dict, trace_id: str, parent: str | None, shared: list[dict]) -> dict:
    body = event["body"]
    start = body.get("startTime") or body.get("timestamp") or event.get("timestamp")
    end = body.get("endTime") or event.get("timestamp") or start
    attributes = list(shared)
    attributes.append(_otel_value(
        "langfuse.observation.type",
        "generation" if event["type"] == "generation-create" else "span",
    ))
    if model := body.get("model"):
        attributes.append(_otel_value("langfuse.observation.model.name", model))
    if usage := body.get("usageDetails"):
        attributes.append(_otel_value("langfuse.observation.usage_details", json.dumps(usage)))
    for name in ("input", "output"):
        if name in body:
            attributes.append(_otel_value(f"langfuse.observation.{name}", body[name]))
    if level := body.get("level"):
        attributes.append(_otel_value("langfuse.observation.level", level))
    if message := body.get("statusMessage"):
        attributes.append(_otel_value("langfuse.observation.status_message", message))
    attributes.extend(_metadata(body.get("metadata") or {}))
    span = {
        "traceId": trace_id,
        "spanId": event["id"][:16],
        "name": str(body.get("name") or "copilot.turn"),
        "kind": 1,
        "startTimeUnixNano": _unix_nano(start),
        "endTimeUnixNano": _unix_nano(end),
        "attributes": attributes,
    }
    if parent:
        span["parentSpanId"] = parent
    return span


def _shared_attributes(root: dict) -> list[dict]:
    values = {
        "langfuse.trace.name": root.get("name"),
        "langfuse.user.id": root.get("userId"),
        "langfuse.session.id": root.get("sessionId"),
        "langfuse.environment": root.get("environment"),
        "langfuse.release": root.get("release"),
    }
    return [_otel_value(key, value) for key, value in values.items() if value]


def _metadata(metadata: dict) -> list[dict]:
    attributes = []
    for key, value in metadata.items():
        if not isinstance(key, str) or not key:
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        attributes.append(_otel_value(f"langfuse.observation.metadata.{key}", text))
        if isinstance(value, str):
            attributes.append(_otel_value(f"langfuse.trace.metadata.{key}", text[:200]))
    return attributes


def _otel_value(key: str, value) -> dict:
    if isinstance(value, bool):
        stored = {"boolValue": value}
    elif isinstance(value, int):
        stored = {"intValue": value}
    elif isinstance(value, float):
        stored = {"doubleValue": value}
    else:
        stored = {"stringValue": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}
    return {"key": key, "value": stored}


def _unix_nano(value: str | None) -> str:
    if not value:
        moment = datetime.now(UTC)
    else:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    return str(int(moment.timestamp() * 1_000_000_000))


async def export_loop(history: History, settings: Settings, delivery: LangfuseDelivery, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            if await history.export_trace(settings.destination, delivery.send):
                continue
        except DatabaseError as exc:
            log.warning("Langfuse outbox unavailable (%s)", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            pass

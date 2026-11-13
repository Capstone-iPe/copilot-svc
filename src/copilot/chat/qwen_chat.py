"""One completion at temperature 0 with thinking off."""

from __future__ import annotations

import json
import logging
import ssl
import time
import urllib.error
import urllib.request

from copilot.chat.chat_model import ChatModel
from copilot.config import chat_api_key, chat_base_url, chat_ca_cert, chat_model
from copilot.words import THINK

log = logging.getLogger("copilot")
_BAD_REQUEST = object()


class QwenChat(ChatModel):
    def complete(self, messages: list[dict], max_tokens: int, schema: dict | None = None) -> str | None:
        key = chat_api_key()
        if not key:
            return None
        model = chat_model()
        body = _body(messages, model, max_tokens, schema)
        base = chat_base_url().rstrip("/")
        reply = _post(base, key, body)
        if reply is _BAD_REQUEST:
            body.pop("response_format", None)
            body.pop("chat_template_kwargs", None)
            reply = _post(base, key, body)
        if not isinstance(reply, str):
            return None
        return THINK.sub("", reply).strip()


def _body(messages: list[dict], model: str, max_tokens: int, schema: dict | None) -> dict:
    body: dict = {
        "model": model,
        "messages": _no_think(messages, model),
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "reply", "schema": schema, "strict": True},
        }
    return body


def _no_think(messages: list[dict], model: str) -> list[dict]:
    """Qwen3 also honours /no_think in the last user message."""
    if "qwen3" not in model.lower() or not messages or messages[-1]["role"] != "user":
        return messages
    last = {**messages[-1], "content": f"{messages[-1]['content']} /no_think"}
    return [*messages[:-1], last]


def _post(base: str, key: str, body: dict):
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    context = ssl.create_default_context(cafile=str(chat_ca_cert()))
    for delay in (0, 2, 4, 8):
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(request, context=context, timeout=60) as response:
                payload = json.load(response)
            return str(payload["choices"][0]["message"]["content"] or "")
        except urllib.error.HTTPError as exc:
            if exc.code == 400 and ("response_format" in body or "chat_template_kwargs" in body):
                return _BAD_REQUEST
            if exc.code not in {429, 503}:
                log.info("chat failed with HTTP %s", exc.code)
                return None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as exc:
            log.info("chat failed (%s)", type(exc).__name__)
            return None
    log.info("chat still busy after retries")
    return None

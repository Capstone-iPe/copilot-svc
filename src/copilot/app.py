"""FastAPI service the FE calls — same routes as copilot-web-app contracts.

  FE --Bearer--> Copilot --Bearer--> ONB

Routes:

  GET  /v1/health
  POST /v1/conversations
  GET  /v1/conversations
  GET  /v1/conversations/{id}
  POST /v1/conversations/{id}/messages
  POST /v1/conversations/{id}/files   (multipart: document + file)

Pills are minimal (upload / submit only). Suggestion chips stay off.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from copilot.adapters.web import WebAdapter, new_message
from copilot.session import Session

SessionFactory = Callable[[str], Awaitable[tuple[Session, dict]]]

log = logging.getLogger("copilot")
app = FastAPI(title="iPe copilot", version="0.1.0")
adapter = WebAdapter()
_start: SessionFactory | None = None



@dataclass
class Conversation:
    id: str
    merchant_id: str
    session: Session
    messages: list[dict] = field(default_factory=list)
    shop_name: str | None = None
    status: str = "DRAFT"
    review_id: str | None = None
    result: dict | None = None
    steps: dict = field(default_factory=dict)
    prompt: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


conversations: dict[str, Conversation] = {}


class MessageBody(BaseModel):
    text: str = ""
    action: str | None = None
    client_message_id: str | None = None


def set_start(start: SessionFactory) -> None:
    global _start
    _start = start
    conversations.clear()


def create_app(start: SessionFactory) -> FastAPI:
    set_start(start)
    return app


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Please sign in again."})
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Please sign in again."})
    return token.strip()


def _merchant(x_merchant_id: str | None) -> str:
    mid = (x_merchant_id or "").strip()
    if not mid:
        raise HTTPException(
            status_code=400,
            detail={"code": "no_merchant", "message": "X-Merchant-Id header is required."},
        )
    return mid


def _refresh_session_bearer(session: Session, bearer: str) -> None:
    token = getattr(session, "access_token", None)
    if token is not None:
        token.set(bearer)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.exception_handler(HTTPException)
async def _http_error(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        return JSONResponse({"error": detail}, status_code=exc.status_code)
    return JSONResponse(
        {"error": {"code": "bad_request", "message": str(detail)}},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def _any_error(_request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(
        {"error": {"code": "bad_request", "message": "Something went wrong opening the chat."}},
        status_code=500,
    )


def _exc_text(exc: BaseException) -> str:
    parts = [str(exc)]
    if isinstance(exc, BaseExceptionGroup):
        for nested in exc.exceptions:
            parts.append(_exc_text(nested))
    cause = exc.__cause__ or exc.__context__
    if isinstance(cause, BaseException):
        parts.append(_exc_text(cause))
    return " ".join(parts)


def _onb_http_error(exc: BaseException) -> HTTPException:
    text = _exc_text(exc).lower()
    if any(token in text for token in ("401", "unauthorized", "invalid_token", "forbidden", "not allowed")):
        return HTTPException(
            status_code=401,
            detail={
                "code": "unauthorized",
                "message": (
                    "ONB rejected the Google token. Use Google sign-in, and on onb-k8ud set "
                    "GOOGLE_ALLOWED_AUDIENCES to the web app's GOOGLE_CLIENT_ID if it differs."
                ),
            },
        )
    return HTTPException(
        status_code=502,
        detail={"code": "onb_unavailable", "message": "Could not open a live ONB session."},
    )


async def _open_session(bearer: str) -> tuple[Session, dict]:
    assert _start is not None
    try:
        return await _start(bearer)
    except Exception as exc:
        raise _onb_http_error(exc) from exc




def _view(conv: Conversation) -> dict:
    return {
        "id": conv.id,
        "shop_name": conv.shop_name,
        "status": conv.status,
        "review_id": conv.review_id,
        "steps": conv.steps,
        "messages": list(conv.messages),
        "prompt": conv.prompt,
        "result": conv.result,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
    }


def _apply_open(conv: Conversation, opened: dict) -> None:
    conv.messages = list(opened.get("messages") or [])
    conv.prompt = opened.get("prompt") or {}
    conv.steps = opened.get("steps") or {}
    conv.shop_name = opened.get("shop_name")
    conv.status = opened.get("status") or "DRAFT"
    conv.review_id = opened.get("review_id")
    conv.result = opened.get("result")
    stamp = new_message("assistant", "").get("created_at")
    conv.created_at = stamp
    conv.updated_at = stamp


def _apply_turn(
    conv: Conversation,
    rendered: dict,
    *,
    merchant_text: str,
    attachments: list | None = None,
) -> dict:
    if merchant_text or attachments:
        merchant = new_message(
            "merchant",
            merchant_text,
            attachments=attachments or [],
        )
        conv.messages.append(merchant)
    reply_msg = None
    texts = rendered.get("assistant_texts") or []
    card = rendered.get("card")
    for i, text in enumerate(texts):
        msg = new_message("assistant", text, card=card if i == len(texts) - 1 else None)
        conv.messages.append(msg)
        reply_msg = msg
    if not texts and card:
        reply_msg = new_message("assistant", "", card=card)
        conv.messages.append(reply_msg)
    conv.prompt = rendered.get("prompt") or {}
    conv.steps = rendered.get("steps") or conv.steps
    conv.status = rendered.get("status") or conv.status
    conv.review_id = rendered.get("review_id")
    conv.result = rendered.get("result")
    if rendered.get("shop_name"):
        conv.shop_name = rendered["shop_name"]
    elif not conv.shop_name and merchant_text and rendered.get("asking") == "city":
        conv.shop_name = merchant_text.strip()
    conv.updated_at = new_message("assistant", "").get("created_at")
    return reply_msg or new_message("assistant", "")


@app.get("/v1/health")
async def health() -> dict:
    return {"ok": True, "agent": "copilot"}


@app.post("/v1/conversations", status_code=201)
async def open_conversation(
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
) -> dict:
    if _start is None:
        raise HTTPException(status_code=500, detail={"code": "bad_request", "message": "start_not_configured"})
    merchant_id = _merchant(x_merchant_id)
    bearer = _bearer(authorization)
    session, step = await _open_session(bearer)
    cid = str(step.get("application_id") or "")
    if not cid or step.get("error"):
        raise HTTPException(
            status_code=502,
            detail={"code": "onb_unavailable", "message": str(step.get("error") or "no_conversation")},
        )
    opened = adapter.open(step)
    conv = Conversation(id=cid, merchant_id=merchant_id, session=session)
    _apply_open(conv, opened)
    conversations[cid] = conv
    return {"conversation": _view(conv)}


@app.get("/v1/conversations")
async def list_conversations(
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
) -> dict:
    _bearer(authorization)
    merchant_id = _merchant(x_merchant_id)
    rows = [
        {
            "id": c.id,
            "shop_name": c.shop_name,
            "status": c.status,
            "review_id": c.review_id,
            "updated_at": c.updated_at,
        }
        for c in conversations.values()
        if c.merchant_id == merchant_id
    ]
    rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    return {"conversations": rows}


@app.get("/v1/conversations/{conversation_id}")
async def load_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
) -> dict:
    _bearer(authorization)
    merchant_id = _merchant(x_merchant_id)
    conv = conversations.get(conversation_id)
    if conv is None or conv.merchant_id != merchant_id:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such conversation."})
    return {"conversation": _view(conv)}


@app.post("/v1/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: MessageBody,
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
) -> dict:
    merchant_id = _merchant(x_merchant_id)
    conv = conversations.get(conversation_id)
    if conv is None or conv.merchant_id != merchant_id:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such conversation."})
    _refresh_session_bearer(conv.session, _bearer(authorization))
    if body.action == "submit":
        line = "submit"
        shown = "Submit application"
    else:
        line = (body.text or "").strip()
        shown = line
    if not line:
        raise HTTPException(status_code=400, detail={"code": "empty_message", "message": "Type a message."})
    try:
        reply = await conv.session.turn(line)
    except Exception as exc:
        raise _onb_http_error(exc) from exc
    rendered = adapter.render(reply, line=line)
    reply_msg = _apply_turn(conv, rendered, merchant_text=shown)
    return {"conversation": _view(conv), "reply": reply_msg}


@app.post("/v1/conversations/{conversation_id}/files")
async def send_file(
    conversation_id: str,
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
    document: str = Form(""),
    file: UploadFile = File(...),
) -> Any:
    merchant_id = _merchant(x_merchant_id)
    conv = conversations.get(conversation_id)
    if conv is None or conv.merchant_id != merchant_id:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No such conversation."})
    _refresh_session_bearer(conv.session, _bearer(authorization))
    name = (file.filename or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail={"code": "no_file", "message": "Choose a file."})
    low = name.lower()
    if not low.endswith((".pdf", ".jpg", ".jpeg", ".png")):
        raise HTTPException(
            status_code=415,
            detail={"code": "unsupported_type", "message": "Only PDF, JPG and PNG files are accepted."},
        )
    # ONB currently stores a file name; bytes are not forwarded yet.
    try:
        reply = await conv.session.turn(name)
    except Exception as exc:
        raise _onb_http_error(exc) from exc
    rendered = adapter.render(reply, line=name)
    reply_msg = _apply_turn(
        conv,
        rendered,
        merchant_text="",
        attachments=[{"document": document or asking_document(conv), "filename": name}],
    )
    return {"conversation": _view(conv), "reply": reply_msg}


def asking_document(conv: Conversation) -> str:
    field = (conv.prompt or {}).get("field")
    return str(field) if field else ""

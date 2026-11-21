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

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from pydantic import BaseModel, Field

from copilot.adapters.web import WebAdapter, asking_for, new_message, prompt_view
from copilot.dialogue import DialogueState
from copilot.history import ConversationBusy, ConversationHistory, History
from copilot.identity import Merchant
from copilot.onb.mcp_onb import OnbAsleep
from copilot.reply import Reply
from copilot.say.questions import answers as stored_answers
from copilot.say.questions import prompt_for
from copilot.session import Session

SessionFactory = Callable[[str, str | None], Awaitable[tuple[Session, dict]]]
MerchantVerifier = Callable[[str], Merchant | None]

log = logging.getLogger("copilot")
router = APIRouter()
adapter = WebAdapter()
NOT_FOUND = {"code": "not_found", "message": "No such conversation."}
INTERRUPTED = (
    "The previous message was interrupted. I refreshed your application and did not resend it. "
    "Check the current step before continuing."
)


class MessageBody(BaseModel):
    text: str = ""
    action: str | None = None
    client_message_id: str | None = Field(default=None, min_length=1, max_length=128)


class OpenBody(BaseModel):
    application_id: str | None = None


def create_app(start: SessionFactory, history: History, verify: MerchantVerifier) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await history.initialize()
        yield

    app = FastAPI(title="iPe copilot", version="0.1.0", lifespan=lifespan)
    app.state.start = start
    app.state.history = history
    app.state.verify = verify
    app.include_router(router)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(ConversationBusy, _conversation_busy)
    app.add_exception_handler(OperationalError, _history_unavailable)
    app.add_exception_handler(Exception, _any_error)
    return app


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Please sign in again."})
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail={"code": "unauthorized", "message": "Please sign in again."})
    return token.strip()


async def _authenticate(request: Request, authorization: str | None, claimed_id: str | None) -> tuple[str, Merchant]:
    bearer = _bearer(authorization)
    merchant = await asyncio.to_thread(request.app.state.verify, bearer)
    if merchant is None or (claimed_id is not None and claimed_id.strip() != merchant.id):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Sign in with the Google account that owns this conversation."},
        )
    return bearer, merchant


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


async def _http_error(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        return JSONResponse({"error": detail}, status_code=exc.status_code)
    return JSONResponse(
        {"error": {"code": "bad_request", "message": str(detail)}},
        status_code=exc.status_code,
    )


async def _conversation_busy(_request: Request, _exc: ConversationBusy) -> JSONResponse:
    return _error(409, "conversation_busy", "This conversation is busy. Retry with the same message ID.")


async def _history_unavailable(_request: Request, exc: OperationalError) -> JSONResponse:
    log.warning("Conversation history is unavailable (%s)", type(exc).__name__)
    return _error(503, "history_unavailable", "Conversation history is unavailable. Try again.")


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


def _onb_http_error(exc: BaseException, *, opening: bool = False) -> HTTPException:
    if isinstance(exc, OnbAsleep):
        return HTTPException(
            status_code=503,
            detail={
                "code": "onb_unavailable",
                "message": "The onboarding service is waking up. Try again in a moment.",
            },
        )
    text = _exc_text(exc).lower()
    # mcp 2.3 often surfaces ONB's 401 as "Server returned an error response" only;
    # connect_bearer rewrites that to invalid_token after a status probe.
    if any(
        token in text
        for token in (
            "401",
            "403",
            "unauthorized",
            "invalid_token",
            "forbidden",
            "not allowed",
            "server returned an error response",
        )
    ):
        return HTTPException(
            status_code=401,
            detail={
                "code": "unauthorized",
                "message": (
                    "ONB rejected the Google access token. Use Google sign-in (not development "
                    "login), and confirm GOOGLE_ALLOWED_EMAILS on onb-k8ud includes this account."
                ),
            },
        )
    short = _exc_text(exc).strip().replace("\n", " ")
    if len(short) > 180:
        short = short[:177] + "..."
    if "corpus" in text:
        return HTTPException(
            status_code=502,
            detail={
                "code": "corpus_unavailable",
                "message": (
                    f"Policy search is unavailable. ({short})"
                    if short
                    else "Policy search is unavailable."
                ),
            },
        )
    head = "Could not open a live ONB session." if opening else "The live ONB call failed."
    return HTTPException(
        status_code=502,
        detail={
            "code": "onb_unavailable",
            "message": f"{head} ({short})" if short else head,
        },
    )


async def _open_session(request: Request, bearer: str, application_id: str | None = None) -> Session:
    try:
        session, step = await request.app.state.start(bearer, application_id)
    except Exception as exc:
        log.exception("live ONB open failed")
        raise _onb_http_error(exc, opening=True) from exc
    cid = step.get("application_id")
    if step.get("error") or not cid or (application_id is not None and cid != application_id):
        raise HTTPException(502, detail={"code": "onb_unavailable", "message": "ONB application could not be opened."})
    return session


def _update_view(view: dict, rendered: dict, dialogue: DialogueState) -> None:
    for key in ("shop_name", "status", "review_id", "result", "steps", "prompt"):
        view[key] = rendered[key]
    waiting = dialogue.awaiting or ""
    kind, _, field = waiting.partition(":")
    if field and kind in {"confirm", "value_for"} and view["status"] == "DRAFT":
        view["prompt"] = prompt_view(field)


def _append_turn(view: dict, merchant_message: dict, rendered: dict) -> dict:
    view["messages"].append(merchant_message)
    card = rendered.get("card")
    texts = rendered["assistant_texts"] or [""]
    replies = [new_message("assistant", text, card=card if i == len(texts) - 1 else None)
               for i, text in enumerate(texts)]
    view["messages"].extend(replies)
    view["updated_at"] = replies[-1]["created_at"]
    return replies[-1]


async def _resume(
    request: Request, record: ConversationHistory, bearer: str,
) -> tuple[Session, str | None]:
    session = await _open_session(request, bearer, record.cid)
    session.dialogue = DialogueState.restore(record.dialogue)
    pending = await record.turn()
    if pending is None:
        return session, None

    # ONB may already have applied some or all of the turn. Never rerun it.
    dialogue = session.dialogue
    before = pending.input["answers"]
    after = _snapshot_answers(session)
    for field, value in after.items():
        if before.get(field) != value:
            dialogue.remember(field, str(value))
    dialogue.awaiting = None
    dialogue.proposed = None
    dialogue.resume_to = None
    dialogue.focus = (session.step.get("pending") or {}).get("name")
    dialogue.note("merchant", pending.input["request"]["line"])
    dialogue.note("assistant", INTERRUPTED)
    text = " ".join(part for part in (INTERRUPTED, prompt_for(session.step)) if part)
    rendered = adapter.render(Reply(text=text, prompt="", trace={}, step=session.step))
    _update_view(record.view, rendered, dialogue)
    reply = _append_turn(record.view, pending.input["message"], rendered)
    await record.finish(pending, reply, record.view, asdict(dialogue))
    log.warning("Reconciled interrupted turn for conversation %s without replay", record.cid)
    return session, pending.key


def _snapshot_answers(session: Session) -> dict:
    return stored_answers(session.step.get("snapshot") or {})


async def _load_view(request: Request, record: ConversationHistory, bearer: str) -> dict:
    session, recovered = await _resume(request, record, bearer)
    if recovered is not None:
        return {"conversation": record.view}
    old = record.view.copy()
    rendered = adapter.render(Reply(text="", prompt="", trace={}, step=session.step))
    _update_view(record.view, rendered, session.dialogue)
    if old != record.view:
        await record.save(record.view, asdict(session.dialogue))
    return {"conversation": record.view}


@router.get("/v1/health")
async def health() -> dict:
    return {"ok": True, "agent": "copilot"}


@router.post("/v1/conversations", status_code=201)
async def open_conversation(
    request: Request,
    body: OpenBody | None = None,
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
) -> JSONResponse:
    bearer, merchant = await _authenticate(request, authorization, x_merchant_id)
    history: History = request.app.state.history
    if body and body.application_id:
        # An application ID supplied by the caller is not proof of ONB ownership.
        async with history.conversation(body.application_id, merchant.id) as record:
            if record is None:
                raise HTTPException(404, detail=NOT_FOUND)
            return JSONResponse(await _load_view(request, record, bearer))

    session = await _open_session(request, bearer)
    cid = session.application_id
    view = adapter.open(session.step, merchant_name=merchant.name)
    view.pop("asking")
    stamp = view["messages"][0]["created_at"]
    view.update(id=cid, created_at=stamp, updated_at=stamp)
    if not await history.create(cid, merchant.id, view, asdict(session.dialogue)):
        raise HTTPException(409, detail={"code": "conversation_exists", "message": "Could not create a new conversation."})
    return JSONResponse({"conversation": view}, status_code=201)


@router.get("/v1/conversations")
async def list_conversations(
    request: Request,
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
) -> dict:
    _, merchant = await _authenticate(request, authorization, x_merchant_id)
    return {"conversations": await request.app.state.history.list(merchant.id)}


@router.get("/v1/conversations/{conversation_id}")
async def load_conversation(
    conversation_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
) -> dict:
    bearer, merchant = await _authenticate(request, authorization, x_merchant_id)
    async with request.app.state.history.conversation(conversation_id, merchant.id) as record:
        if record is None:
            raise HTTPException(404, detail=NOT_FOUND)
        return await _load_view(request, record, bearer)


async def _run_turn(
    request: Request,
    cid: str,
    bearer: str,
    owner: str,
    key: str | None,
    turn_request: dict,
) -> dict:
    async with request.app.state.history.conversation(cid, owner) as record:
        if record is None:
            raise HTTPException(404, detail=NOT_FOUND)
        turn = await record.turn(key) if key is not None else None
        if turn is not None:
            if turn.input["request"] != turn_request:
                raise HTTPException(409, detail={
                    "code": "message_id_reused", "message": "Message ID was used for different input.",
                })
            if turn.reply is not None:
                return {"conversation": record.view, "reply": turn.reply}
        session, recovered = await _resume(request, record, bearer)
        if recovered is not None:
            if recovered == key:
                completed = await record.turn(recovered)
                assert completed is not None and completed.reply is not None
                return {"conversation": record.view, "reply": completed.reply}
            raise HTTPException(409, detail={"code": "turn_interrupted", "message": INTERRUPTED})
        line = turn_request["line"]
        document = turn_request.get("document")
        attachments = (
            [{"document": document or asking_for(session.step) or "", "filename": line}]
            if turn_request["kind"] == "file" else []
        )
        message = new_message("merchant", turn_request["text"], attachments=attachments)
        turn = await record.reserve(key or f"server:{uuid4()}", {
            "request": turn_request, "message": message, "answers": _snapshot_answers(session),
        })
        try:
            reply = await session.turn(line)
        except Exception as exc:
            log.exception("live ONB turn failed conversation_id=%s", cid)
            raise _onb_http_error(exc) from exc
        rendered = adapter.render(reply, line=line)
        _update_view(record.view, rendered, session.dialogue)
        reply_msg = _append_turn(record.view, message, rendered)
        await record.finish(turn, reply_msg, record.view, asdict(session.dialogue))
        return {"conversation": record.view, "reply": reply_msg}


@router.post("/v1/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: MessageBody,
    request: Request,
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
) -> dict:
    bearer, merchant = await _authenticate(request, authorization, x_merchant_id)
    if body.action == "submit":
        line = "submit"
        shown = "Submit application"
    else:
        line = (body.text or "").strip()
        shown = line
    if not line:
        raise HTTPException(status_code=400, detail={"code": "empty_message", "message": "Type a message."})
    key = f"client:{body.client_message_id}" if body.client_message_id is not None else None
    return await _run_turn(request, conversation_id, bearer, merchant.id, key,
                           {"kind": "message", "line": line, "text": shown, "action": body.action})


@router.post("/v1/conversations/{conversation_id}/files")
async def send_file(
    conversation_id: str,
    request: Request,
    file: Annotated[UploadFile, File()],
    authorization: str | None = Header(default=None),
    x_merchant_id: str | None = Header(default=None),
    document: str = Form(""),
    client_message_id: str | None = Form(None, min_length=1, max_length=128),
) -> dict:
    bearer, merchant = await _authenticate(request, authorization, x_merchant_id)
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
    key = f"client:{client_message_id}" if client_message_id is not None else None
    return await _run_turn(request, conversation_id, bearer, merchant.id, key,
                           {"kind": "file", "line": name, "text": "", "document": document})

"""FastAPI service the FE calls.

  FE --Bearer--> Copilot --Bearer--> ONB

The FE refreshes Google. Copilot only forwards the access token.

Routes:

  GET  /v1/health
  POST /v1/conversations                 open one chat, return the first prompt
  POST /v1/conversations/{id}/messages   one merchant line
  POST /v1/conversations/{id}/files      one file name as the merchant line

Vanilla Session owns the turn. WebAdapter shapes the JSON. CLI and replay are
internal and do not go through this app.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from copilot.adapters.web import WebAdapter
from copilot.session import Session

SessionFactory = Callable[[str], Awaitable[tuple[Session, dict]]]

app = FastAPI(title="iPe copilot", version="0.1.0")
sessions: dict[str, Session] = {}
adapter = WebAdapter()
_start: SessionFactory | None = None

class MessageBody(BaseModel):
    text: str = Field(min_length=1)

class FileBody(BaseModel):
    file: str = Field(min_length=1)

def set_start(start: SessionFactory) -> None:
    """Wire how a new Session is opened. Tests and __main__ call this."""
    global _start
    _start = start
    sessions.clear()

def create_app(start: SessionFactory) -> FastAPI:
    """Configure the module app and return it. Same object every time."""
    set_start(start)
    return app

def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing_bearer")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing_bearer")
    return token.strip()

def _refresh_session_bearer(session: Session, bearer: str) -> None:
    token = getattr(session, "access_token", None)
    if token is not None:
        token.set(bearer)

@app.get("/v1/health")
async def health() -> dict:
    return {"ok": True}

@app.post("/v1/conversations", status_code=201)
async def open_conversation(authorization: str | None = Header(default=None)) -> dict:
    if _start is None:
        raise HTTPException(status_code=500, detail="start_not_configured")
    bearer = _bearer(authorization)
    session, step = await _start(bearer)
    conversation_id = str(step.get("application_id") or "")
    if not conversation_id or step.get("error"):
        raise HTTPException(status_code=502, detail=str(step.get("error") or "no_conversation"))
    sessions[conversation_id] = session
    body = adapter.open(step)
    body["conversation_id"] = conversation_id
    return body

@app.post("/v1/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: MessageBody,
    authorization: str | None = Header(default=None),
) -> dict:
    session = sessions.get(conversation_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown_conversation")
    _refresh_session_bearer(session, _bearer(authorization))
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty_message")
    reply = await session.turn(text)
    out = adapter.render(reply, line=text)
    out["conversation_id"] = conversation_id
    return out

@app.post("/v1/conversations/{conversation_id}/files")
async def send_file(
    conversation_id: str,
    body: FileBody,
    authorization: str | None = Header(default=None),
) -> dict:
    session = sessions.get(conversation_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown_conversation")
    _refresh_session_bearer(session, _bearer(authorization))
    name = body.file.strip()
    if not name:
        raise HTTPException(status_code=400, detail="empty_file")
    reply = await session.turn(name)
    out = adapter.render(reply, line=name)
    out["conversation_id"] = conversation_id
    return out

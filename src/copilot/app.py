"""FastAPI service the FE calls.

Shape (auth and history come later):

  FE --Bearer--> Copilot --Bearer--> ONB

Routes now:

  GET  /v1/health
  POST /v1/conversations                 open one chat, return the first prompt
  POST /v1/conversations/{id}/messages   one merchant line
  POST /v1/conversations/{id}/files      one file name as the merchant line

Vanilla Session owns the turn. WebAdapter shapes the JSON. CLI and replay are
internal and do not go through this app.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from copilot.adapters.web import WebAdapter
from copilot.session import Session

SessionFactory = Callable[[], Awaitable[tuple[Session, dict]]]

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

@app.get("/v1/health")
async def health() -> dict:
    return {"ok": True}

@app.post("/v1/conversations", status_code=201)
async def open_conversation() -> dict:
    # Auth: validate FE bearer, then open ONB with a bearer. Later.
    if _start is None:
        raise HTTPException(status_code=500, detail="start_not_configured")
    session, step = await _start()
    conversation_id = str(step.get("application_id") or "")
    if not conversation_id or step.get("error"):
        raise HTTPException(status_code=502, detail=str(step.get("error") or "no_conversation"))
    sessions[conversation_id] = session
    body = adapter.open(step)
    body["conversation_id"] = conversation_id
    return body

@app.post("/v1/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: MessageBody) -> dict:
    session = sessions.get(conversation_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown_conversation")
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty_message")
    reply = await session.turn(text)
    out = adapter.render(reply, line=text)
    out["conversation_id"] = conversation_id
    return out

@app.post("/v1/conversations/{conversation_id}/files")
async def send_file(conversation_id: str, body: FileBody) -> dict:
    session = sessions.get(conversation_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown_conversation")
    name = body.file.strip()
    if not name:
        raise HTTPException(status_code=400, detail="empty_file")
    reply = await session.turn(name)
    out = adapter.render(reply, line=name)
    out["conversation_id"] = conversation_id
    return out

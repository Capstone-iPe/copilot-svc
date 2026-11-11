"""Web-consumable routes over vanilla Session + WebAdapter.

GET  /v1/health
POST /v1/applications              -> open one application, return the first prompt
POST /v1/applications/{id}/messages  body {"text": "..."} -> one turn
POST /v1/applications/{id}/files     body {"file": "name.pdf"} -> one turn with that file name

The process holds Session objects in memory. Wire ONB through the factory you pass in.
"""

from __future__ import annotations

import os
from typing import Awaitable, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from copilot.adapters.web import WebAdapter
from copilot.session import Session

SessionFactory = Callable[[], Awaitable[tuple[Session, dict]]]


def create_app(start: SessionFactory) -> Starlette:
    sessions: dict[str, Session] = {}
    adapter = WebAdapter()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def open_application(_: Request) -> JSONResponse:
        session, step = await start()
        application_id = str(step.get("application_id") or "")
        if not application_id or step.get("error"):
            return JSONResponse({"error": step.get("error") or "no_application"}, status_code=502)
        sessions[application_id] = session
        body = adapter.open(step)
        return JSONResponse(body, status_code=201)

    async def send_message(request: Request) -> JSONResponse:
        application_id = request.path_params["application_id"]
        session = sessions.get(application_id)
        if session is None:
            return JSONResponse({"error": "unknown_application"}, status_code=404)
        payload = await request.json()
        text = str(payload.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "empty_message"}, status_code=400)
        reply = await session.turn(text)
        return JSONResponse(adapter.render(reply, line=text))

    async def send_file(request: Request) -> JSONResponse:
        application_id = request.path_params["application_id"]
        session = sessions.get(application_id)
        if session is None:
            return JSONResponse({"error": "unknown_application"}, status_code=404)
        payload = await request.json()
        name = str(payload.get("file") or "").strip()
        if not name:
            return JSONResponse({"error": "empty_file"}, status_code=400)
        reply = await session.turn(name)
        return JSONResponse(adapter.render(reply, line=name))

    return Starlette(
        routes=[
            Route("/v1/health", health, methods=["GET"]),
            Route("/v1/applications", open_application, methods=["POST"]),
            Route("/v1/applications/{application_id}/messages", send_message, methods=["POST"]),
            Route("/v1/applications/{application_id}/files", send_file, methods=["POST"]),
        ]
    )


def main() -> None:
    """Local run. Uses in-process ONB from the Capstone checkout when COPILOT_HTTP=memory."""
    import uvicorn

    from copilot.http.memory import memory_start

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(create_app(memory_start), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()

"""Start the FastAPI copilot service against live ONB MCP.

  PYTHONPATH=src .venv/bin/python -m copilot

FE sends Authorization: Bearer <Google access token>. Copilot forwards it to ONB.
Binds 0.0.0.0:$PORT for Render. USE_MEMORY_ONB=1 keeps the laptop MemoryOnb path.
"""

from __future__ import annotations

import asyncio
import os
import sys
from functools import partial

import uvicorn
from dotenv import load_dotenv

from copilot.app import create_app
from copilot.history import History
from copilot.identity import verify_merchant


def main() -> None:
    load_dotenv()
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL is required for the Copilot web service.")
    audiences = frozenset(
        value.strip() for key in ("GOOGLE_CLIENT_ID", "GOOGLE_ALLOWED_AUDIENCES")
        for value in os.environ.get(key, "").split(",") if value.strip()
    )
    if not audiences:
        raise SystemExit("Set GOOGLE_CLIENT_ID or GOOGLE_ALLOWED_AUDIENCES to verify Google access tokens.")

    if os.environ.get("USE_MEMORY_ONB", "").strip() in {"1", "true", "yes"}:
        from copilot.local import local_start as start
    else:
        from copilot.live import live_start as start

    app = create_app(start, History(dsn), partial(verify_merchant, audiences=audiences))
    port = int(os.environ.get("PORT", "8080"))
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port))
    # Psycopg's async connections need a selector loop on Windows.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(server.serve())


if __name__ == "__main__":
    main()

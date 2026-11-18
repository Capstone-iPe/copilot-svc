"""Start the FastAPI copilot service against live ONB MCP.

  PYTHONPATH=src .venv/bin/python -m copilot

Set ONB_MCP_BEARER, or GOOGLE_REFRESH_TOKEN + GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET.
Binds 0.0.0.0:$PORT for Render. USE_MEMORY_ONB=1 keeps the laptop MemoryOnb path.
"""

from __future__ import annotations

import os

import uvicorn

from copilot.app import app, set_start


def main() -> None:
    if os.environ.get("USE_MEMORY_ONB", "").strip() in {"1", "true", "yes"}:
        from copilot.local import local_start

        set_start(local_start)
    else:
        from copilot.live import live_start

        set_start(live_start)
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()

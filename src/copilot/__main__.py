"""Start the FastAPI copilot service.

  PYTHONPATH=src:replay .venv/bin/python -m copilot

Uses local in-process ONB until the deploy start wires live ONB with a bearer.
Binds 0.0.0.0:$PORT for Render.
"""

from __future__ import annotations

import os

import uvicorn

from copilot.app import app, set_start
from copilot.local import local_start


def main() -> None:
    set_start(local_start)
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()

"""Loopback callback and the token holder. Tokens stay in memory."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class Tokens:
    def __init__(self) -> None:
        self.tokens = None
        self.client_info = None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens) -> None:
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info) -> None:
        self.client_info = client_info


class Wait:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.box: dict = {}
        self.server: ThreadingHTTPServer | None = None


def loopback() -> tuple[str, Wait]:
    waiter = Wait()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(waiter))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    waiter.server = server
    return f"http://127.0.0.1:{port}/callback", waiter


def _handler(waiter: Wait):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            _receive(self, waiter)

        def log_message(self, _format: str, *_args) -> None:
            return

    return Handler


def _receive(handler: BaseHTTPRequestHandler, waiter: Wait) -> None:
    parsed = urlparse(handler.path)
    if parsed.path != "/callback":
        handler.send_response(404)
        handler.end_headers()
        return
    query = parse_qs(parsed.query)
    waiter.box = {
        "code": (query.get("code") or [""])[0],
        "state": (query.get("state") or [None])[0],
        "iss": (query.get("iss") or [None])[0],
        "error": (query.get("error") or [None])[0],
    }
    body = b"Signed in. You can close this window."
    handler.send_response(200)
    handler.send_header("Content-Type", "text/plain")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    waiter.ready.set()

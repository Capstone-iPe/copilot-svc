#!/usr/bin/env python3
"""Command-line copilot for one shop.

It signs in through ONB, which opens Google in the browser. It calls ONB's five
tools and searches the local corpus index. Quit is the only line handled here.
Every other line goes to the chat model, which names the action. A second call
phrases a "why?" answer or the result. The model does not pick the next field
or change the verdict.

The application id lives in this process only. A new run starts a new application.

    python copilot.py --index index

Chat settings, all from the environment, none written here:

    CHAT_API_KEY    bearer token
    CHAT_MODEL      defaults to Qwen/Qwen3-8B

Type the answer to the question on screen. Other lines:

    why?                         explain, then ask the same question
    registration.pdf             the file name for the upload on screen
    I don't have this            close that upload
    monthly_volume=₹39,00,000    replace a stored answer before submit
    submit                       run the rules
    review                       read the review already stored
    quit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from index_corpus import MODEL, load_index, merge, tokens

log = logging.getLogger("copilot")
HERE = Path(__file__).resolve().parent
QUESTIONS = {
    "shop_name": "What is the shop's legal name?",
    "city": "Which city is the shop in?",
    "business_type": "What kind of shop is it?",
    "monthly_volume": "What is the expected monthly volume, in rupees? Use digits, such as ₹12,00,000.",
    "payment_methods": "Which payment methods will the shop take?",
    "stores_payer_phones": "Will the shop store payer phone numbers? Yes or no.",
    "note": "Any note to add? You can say no note.",
}
UPLOADS = {
    "business_registration": "Upload the business registration. Type a PDF, JPG, or PNG file name.",
    "owner_id": "Upload the owner's government ID. Type a PDF, JPG, or PNG file name.",
    "bank_proof": "Upload bank proof in the shop's legal name. Type a PDF, JPG, or PNG file name.",
    "shopfront_photo": "Upload a shopfront photo from the last 90 days. Type a PDF, JPG, or PNG file name.",
    "dpa_addendum": "Upload the signed data-processing addendum. Type a PDF, JPG, or PNG file name.",
}
FILE_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
REVIEW_ID = re.compile(r"MR-\d+")
LIVE_WORDS = re.compile(r"\b(activated|activation)\b|\bis live\b", re.I)
OUTCOME_WORDS = {
    "IN_REVIEW": "The shop stays in review.",
    "RECOMMEND_GO_LIVE": "Go-live may be recommended.",
    "REFUSED": "The application is refused.",
}
ASSIGNEE_WORDS = {
    "MERCHANT_RISK_LEAD": "Merchant Risk Lead",
    "HEAD_OF_PAYMENTS": "Head of Payments",
}


def question_for(pending: dict | None) -> str:
    if not pending:
        return "Submit when you're ready."
    name = str(pending.get("name") or "")
    if pending.get("kind") == "upload":
        return UPLOADS.get(name, f"Upload {name}.")
    return QUESTIONS.get(name, name)


def _file_name(line: str) -> str | None:
    name = Path(line.strip()).name
    if Path(name).suffix.lower() in FILE_SUFFIXES:
        return name
    return None


def _upload_slot(pending: dict | None, open_slots: list[str]) -> str | None:
    if pending and pending.get("kind") == "upload":
        return str(pending["name"])
    if len(open_slots) == 1:
        return open_slots[0]
    return None


def choose(line: str) -> dict:
    """Quit stays here. Every other line goes to the model."""
    if line.strip().lower() in {"quit", "exit"}:
        return {"action": "quit"}
    return {"action": "ask"}


def apply_decision(
    line: str,
    decision: dict,
    pending: dict | None,
    held: bool,
    open_slots: list[str],
) -> dict:
    """Turn the model's action into one tool call. The pending field stays the one ONB named."""
    action = str(decision.get("action") or "")
    if action == "question":
        return {"action": "why"}
    if action == "submit":
        return {"action": "submit"}
    if action == "review":
        return {"action": "review"}
    slot = _upload_slot(pending, open_slots)
    if action == "missing" and slot:
        return {"action": "missing", "slot": slot}
    if action == "file" and slot:
        name = _file_name(str(decision.get("file") or line))
        if name:
            return {"action": "file", "slot": slot, "file": name}
    if action == "replace" and not held:
        field = str(decision.get("field") or "").strip()
        value = str(decision.get("value") or "").strip()
        if field and value:
            return {"action": "save", "field": field, "value": value}
    if action == "answer" and pending and pending.get("kind") == "field":
        return {"action": "save", "field": pending["name"], "value": line.strip()}
    if action == "answer" and slot:
        name = _file_name(line)
        if name:
            return {"action": "file", "slot": slot, "file": name}
    return {"action": "again"}


def classify_line(line: str, pending_question: str, pending: dict | None, held: bool) -> dict:
    """One model call. It names the action. It does not call a tool."""
    reply = chat(
        [
            {
                "role": "system",
                "content": (
                    "Reply with one JSON object and nothing else. "
                    '{"action":"question"} they are asking why this is needed, or what a word means. '
                    '{"action":"answer"} the line is the answer to the pending field. Do not rewrite it. '
                    '{"action":"missing"} they do not have the file, or they want to skip it. '
                    '{"action":"file","file":"name.pdf"} they named a PDF, JPG, or PNG. '
                    '{"action":"replace","field":"city","value":"Pune"} they are changing an answer already given. '
                    '{"action":"submit"} they asked to submit. '
                    '{"action":"review"} they asked for the review reference, or to activate.'
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "asked": pending_question,
                        "said": line,
                        "pending": pending,
                        "verdict_stored": held,
                    }
                ),
            },
        ]
    )
    if not reply:
        log.info("model returned nothing")
        return {}
    log.info("model %s", " ".join(reply.split()))
    start = reply.find("{")
    end = reply.rfind("}")
    if start < 0 or end < start:
        log.info("model reply was not JSON")
        return {}
    try:
        parsed = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        log.info("model reply was not JSON")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def acceptable(sentence: str, facts: dict) -> bool:
    blob = json.dumps(facts)
    if LIVE_WORDS.search(sentence):
        return False
    return all(found in blob for found in REVIEW_ID.findall(sentence))


def plain_reply(facts: dict) -> str:
    verdict = facts.get("verdict") if isinstance(facts.get("verdict"), dict) else None
    if verdict:
        words = OUTCOME_WORDS.get(str(verdict.get("outcome")), "The result is stored.")
        review_id = verdict.get("review_id")
        if review_id:
            words += f" Review {review_id}."
        assignee = ASSIGNEE_WORDS.get(str(verdict.get("assignee") or ""))
        if assignee:
            words += f" For the {assignee}."
        missing = verdict.get("missing_items") or []
        if missing:
            words += " Still missing: " + ", ".join(str(item) for item in missing) + "."
        citations = verdict.get("citations") or []
        if citations:
            words += " " + ", ".join(str(item) for item in citations) + "."
        return words
    passages = facts.get("passages") or []
    if passages:
        names = ", ".join(str(row.get("document_id")) for row in passages[:3])
        return f"See {names}."
    if facts.get("error"):
        return f"That was not stored ({facts['error']})."
    if facts.get("state"):
        return f"The {facts.get('slot')} is {facts['state']}."
    if facts.get("field"):
        return "Stored."
    return "Stored."


CHAT_BASE_URL = "https://103.42.50.41:1032/v1"
CHAT_CA_CERT = HERE / "vm06-ca.crt"


def chat(messages: list[dict]) -> str | None:
    """One completion. Returns None when the key is missing."""
    key = os.environ.get("CHAT_API_KEY", "").strip()
    if not key:
        return None
    body = json.dumps(
        {
            "model": os.environ.get("CHAT_MODEL", "Qwen/Qwen3-8B"),
            "messages": messages,
            "max_tokens": 512,
        }
    ).encode()
    request = urllib.request.Request(
        f"{CHAT_BASE_URL}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    context = ssl.create_default_context(cafile=str(CHAT_CA_CERT))
    for delay in (0, 2, 4, 8):
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(request, context=context, timeout=60) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 503} or delay == 8:
                raise
    else:
        return None
    return str(payload["choices"][0]["message"]["content"]).strip()


def phrase(facts: dict, pending_question: str) -> str:
    log.info("phrase")
    passages = facts.get("passages") or []
    quoted = "\n\n".join(
        f"{row['document_id']}\n{row['text']}" for row in passages[:3]
    )
    asked = chat(
        [
            {
                "role": "system",
                "content": (
                    "Phrase one short reply for the merchant. Use only the facts and the passages. "
                    "Do not say the shop is live. Do not invent a review number. "
                    "Do not add a document or a rule that is not in the facts."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"facts": _public_facts(facts), "passages": quoted, "then_ask": pending_question}),
            },
        ]
    )
    if asked and acceptable(asked, facts):
        return asked
    return plain_reply(facts)


def _public_facts(facts: dict) -> dict:
    """Drop passage text from the fact object the check compares against."""
    shown = {key: value for key, value in facts.items() if key != "passages"}
    if facts.get("passages"):
        shown["document_ids"] = [row.get("document_id") for row in facts["passages"]]
    return shown


class Corpus:
    def __init__(self, index: Path) -> None:
        from rank_bm25 import BM25Okapi
        from sentence_transformers import SentenceTransformer
        import numpy as np

        self.rows, vectors = load_index(index)
        self.vectors = vectors
        self.model = SentenceTransformer(MODEL, local_files_only=True)
        self.keyword = BM25Okapi([tokens(row["text"]) for row in self.rows])
        self.np = np

    def search(self, query: str, k: int = 4) -> list[dict]:
        query_vector = self.model.encode([query], normalize_embeddings=True)[0]
        vector_order = self.np.argsort(-(self.vectors @ query_vector)).tolist()
        keyword_order = self.np.argsort(-self.keyword.get_scores(tokens(query))).tolist()
        found = []
        for row_id in merge(vector_order, keyword_order):
            row = self.rows[row_id]
            if not row["in_force"]:
                continue
            found.append(row)
            if len(found) == k:
                break
        log.info("search %s", [row["document_id"] for row in found])
        return found


def tool_payload(result: object) -> dict:
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise RuntimeError("The tool result was empty.")


def open_slots(snapshot: dict) -> list[str]:
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    return [slot for slot, file in files.items() if isinstance(file, dict) and file.get("state") != "accepted"]


class _Tokens:
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


def _loopback() -> tuple[str, _Wait]:
    waiter = _Wait()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            waiter.box = {
                "code": (query.get("code") or [""])[0],
                "state": (query.get("state") or [None])[0],
                "iss": (query.get("iss") or [None])[0],
                "error": (query.get("error") or [None])[0],
            }
            body = b"Signed in. You can close this window."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            waiter.ready.set()

        def log_message(self, _format: str, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    waiter.server = server
    return f"http://127.0.0.1:{port}/callback", waiter


class _Wait:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.box: dict = {}
        self.server: ThreadingHTTPServer | None = None


async def connect(mcp_url: str):
    import httpx2
    from mcp import Implementation
    from mcp.client.auth import OAuthClientProvider
    from mcp.client.client import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata

    redirect_uri, waiter = _loopback()

    async def redirect(url: str) -> None:
        print("Opening the browser to sign in with Google.")
        print(url)
        webbrowser.open(url)

    async def callback() -> AuthorizationCodeResult:
        await asyncio.to_thread(waiter.ready.wait)
        if waiter.box.get("error") or not waiter.box.get("code"):
            raise RuntimeError(waiter.box.get("error") or "Google sign-in did not return a code.")
        return AuthorizationCodeResult(
            code=waiter.box["code"],
            state=waiter.box["state"],
            iss=waiter.box["iss"],
        )

    auth = OAuthClientProvider(
        server_url=mcp_url,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[redirect_uri],
            client_name="iPe copilot",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="openid email",
            token_endpoint_auth_method="client_secret_post",
        ),
        storage=_Tokens(),
        redirect_handler=redirect,
        callback_handler=callback,
    )
    http = httpx2.AsyncClient(auth=auth, follow_redirects=False, timeout=60)
    transport = streamable_http_client(mcp_url, http_client=http)
    client = Client(transport, client_info=Implementation(name="ipe-copilot", version="0.0.1"))
    await client.__aenter__()
    return client, http, waiter


async def call(client, name: str, arguments: dict) -> dict:
    result = tool_payload(await client.call_tool(name, arguments))
    shown = {key: value for key, value in arguments.items() if key not in {"value", "application_id"}}
    if result.get("error"):
        shown["error"] = result["error"]
    log.info("tool %s %s", name, shown)
    return result


async def run(mcp_url: str, index: Path) -> None:
    corpus = Corpus(index)
    client, http, waiter = await connect(mcp_url)
    application_id = None
    try:
        step = await call(client, "next_step", {})
        if step.get("error"):
            print(plain_reply(step))
            return
        application_id = step["application_id"]
        print(question_for(step.get("pending")))
        while True:
            try:
                line = input("> ")
            except EOFError:
                break
            pending = step.get("pending") if isinstance(step.get("pending"), dict) else None
            snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
            held = isinstance(snapshot.get("verdict"), dict)
            if choose(line)["action"] == "quit":
                break
            if not line.strip():
                print(question_for(pending))
                continue
            action = apply_decision(
                line,
                classify_line(line, question_for(pending), pending, held),
                pending,
                held,
                open_slots(snapshot),
            )
            log.info("do %s", {key: value for key, value in action.items() if key != "value"})
            if action["action"] == "again":
                print(question_for(pending))
                continue
            if action["action"] == "why":
                query = question_for(pending)
                facts = {"passages": corpus.search(query)}
                print(phrase(facts, query))
                print(query)
                continue
            if action["action"] == "save":
                facts = await call(
                    client,
                    "save_answer",
                    {"application_id": application_id, "field": action["field"], "value": action["value"]},
                )
            elif action["action"] == "file":
                facts = await call(
                    client,
                    "save_file",
                    {"application_id": application_id, "slot": action["slot"], "file": action["file"]},
                )
            elif action["action"] == "missing":
                facts = await call(
                    client,
                    "save_file",
                    {"application_id": application_id, "slot": action["slot"], "missing": True},
                )
            elif action["action"] == "submit":
                facts = await call(client, "submit", {"application_id": application_id})
            else:
                facts = await call(client, "get_review", {"application_id": application_id})
            if isinstance(facts.get("verdict"), dict):
                citations = " ".join(facts["verdict"].get("citations") or [])
                facts["passages"] = corpus.search(citations) if citations else []
                print(phrase(facts, ""))
            else:
                print(plain_reply(facts))
            step = await call(client, "next_step", {"application_id": application_id})
            print(question_for(step.get("pending") if isinstance(step.get("pending"), dict) else None))
    finally:
        await client.__aexit__(None, None, None)
        await http.aclose()
        if waiter.server is not None:
            waiter.server.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    parser = argparse.ArgumentParser(description="Talk to ONB as the copilot.")
    parser.add_argument("--mcp", default=os.environ.get("ONB_MCP_URL", "https://onb-k8ud.onrender.com/mcp"))
    parser.add_argument("--index", type=Path, default=HERE / "index")
    args = parser.parse_args()
    asyncio.run(run(args.mcp, args.index))


if __name__ == "__main__":
    main()

# iPe copilot service

Merchant onboarding copilot: hosted ≤8B chat (`Qwen/Qwen3-8B`), remote RAG via [onb-corpus](https://github.com/Capstone-iPe/onb-corpus), MCP client to [onb-svc](https://github.com/Capstone-iPe/onb-svc).

The policy pack and search index live in **onb-corpus**. This service does not vendor documents or build an index. Application state and the verdict live in **ONB**.

## Clone layout

```text
Capstone-iPe/
  copilot-svc/     # this repo
  onb-svc/         # required for MemoryOnb replay
ipe/               # sibling of Capstone-iPe; eval/cases + eval/README.md for replay
```

```bash
git clone https://github.com/Capstone-iPe/copilot-svc.git
cd copilot-svc
```

## Config

```bash
cp .env.example .env
# fill CHAT_API_KEY and CORPUS_API_KEY
```

Place `vm06-ca.crt` at the repo root locally (gitignored). On Render, mount it as a secret file and set `CHAT_CA_CERT=/etc/secrets/vm06-ca.crt`. Never commit the CA.

| Variable | Purpose |
|---|---|
| `CHAT_API_KEY` | Hosted chat completions |
| `CHAT_BASE_URL` | OpenAI-compatible base URL |
| `CHAT_CA_CERT` | TLS CA for the chat host (local `vm06-ca.crt`; Render secret path) |
| `CHAT_MODEL` | Default `Qwen/Qwen3-8B` |
| `ONB_MCP_URL` | Live ONB MCP endpoint (CLI / web) |
| `CORPUS_SEARCH_URL` | onb-corpus base URL |
| `CORPUS_API_KEY` | Bearer for `/v1/search` (same secret as onb-corpus) |
| `DATABASE_URL` | Required for FastAPI: shared PostgreSQL connection string |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID used by the web UI. `GOOGLE_ALLOWED_AUDIENCES` lists extra client IDs. A token issued for any other client is rejected with 403 |
| `GOOGLE_ALLOWED_EMAILS` | Gmail addresses. Applied only when `GOOGLE_ENFORCE_ALLOWED_EMAILS` is `1`, `true`, `yes`, or `on`. The flag is off on the live service |
| `REDIS_URL` | Render Key Value. Empty locally: no rate limit and no search cache |
| `COPILOT_RATE_LIMIT` | Messages and file uploads per signed-in merchant per UTC minute. Default 30 |
| `COPILOT_SEARCH_CACHE_TTL` | Seconds to reuse an identical policy search. Default 300. Empty hit lists are not cached |

## Setup

Python 3.12. The FastAPI process also needs PostgreSQL 16 and a Google OAuth web client id.

```bash
git clone https://github.com/Capstone-iPe/copilot-svc.git
cd copilot-svc
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
createdb ipe_copilot
cp .env.example .env
```

Place `vm06-ca.crt` in this directory. The file is gitignored.

## Run locally with the other services

Clone [onb-corpus](https://github.com/Capstone-iPe/onb-corpus), [onb-svc](https://github.com/Capstone-iPe/onb-svc), and [copilot-web-app](https://github.com/Capstone-iPe/copilot-web-app) next to this repository, and start corpus (port 8081) and ONB (port 8000) first. The [analysis README](https://github.com/Capstone-iPe/analysis#run-the-services-locally) lists the shared Google client, the two hosted keys, and the CA files.

In this repository's `.env`, point the service at those local processes:

```bash
ONB_MCP_URL=http://127.0.0.1:8000/mcp
CORPUS_SEARCH_URL=http://127.0.0.1:8081
CORPUS_API_KEY=<the same secret as onb-corpus>
DATABASE_URL=postgresql://localhost:5432/ipe_copilot
GOOGLE_CLIENT_ID=<the same client id as the website and ONB>
CHAT_API_KEY=<issued chat key>
CHAT_CA_CERT=vm06-ca.crt
CHAT_BASE_URL=https://103.42.50.41:1032/v1
CHAT_MODEL=Qwen/Qwen3-8B
COPILOT_LANGFUSE_ENABLED=false
```

Leave `REDIS_URL` empty. A laptop then has no rate limit and no search cache. Leave the Langfuse keys empty while `COPILOT_LANGFUSE_ENABLED` is `false`.

```bash
PYTHONPATH=src .venv/bin/python -m copilot
```

The process listens on `http://0.0.0.0:8080`. `curl -sS http://127.0.0.1:8080/v1/health` answers when it is up. It refuses to start until `DATABASE_URL` is set and `GOOGLE_CLIENT_ID` (or `GOOGLE_ALLOWED_AUDIENCES`) is set. It creates `copilot_conversations`, `copilot_turns`, and `copilot_trace_outbox` on startup. The database role needs permission to create tables. Ctrl+C stops it. The next start reads the same Postgres database.

The website then uses `CHAT_SERVICE_URL=http://127.0.0.1:8080`. A merchant signs in with Google on that site. This service checks the access token with Google and forwards it to ONB. The test-merchant button in the website is for the website's mock chat, and this service rejects it.

Corpus must be reachable at `CORPUS_SEARCH_URL` before a question that searches policy. ONB must be reachable at `ONB_MCP_URL` before a turn that saves an answer.

## Run the CLI

Talks to live ONB over MCP (browser Google sign-in once):

```bash
PYTHONPATH=src .venv/bin/python -m copilot.cli
# or: PYTHONPATH=src .venv/bin/python -m copilot.cli --mcp "$ONB_MCP_URL"
```

Type answers one field at a time. `why` / `can you explain?` re-asks with RAG. `submit` runs after the pack (and optional note). `quit` exits.

Closed fields: `business_type`, `payment_methods`, and `stores_payer_phones` must match the allowed sets (see `src/copilot/action/closed.py`). `shop_name` and `city` stay free text.

## Eval replay (no Google sign-in)

Uses in-process ONB (`replay/memory_onb.py` looks for a sibling `onb-svc`) and the gold shops in a sibling `analysis/eval`.

```bash
# Build set G-001–G-050 (gate ≥95%)
PYTHONPATH=src:replay .venv/bin/python replay/run.py | tee docs/results/replay-build.txt

# Holdout G-051–G-071 once (gate ≥90%)
PYTHONPATH=src:replay .venv/bin/python replay/run.py --holdout | tee docs/results/replay-holdout.txt

# One case
PYTHONPATH=src:replay .venv/bin/python replay/run.py --only G-001
```

### Why / ask lines

```bash
PYTHONPATH=src:replay .venv/bin/python replay/questions_run.py | tee docs/results/questions.txt
PYTHONPATH=src:replay .venv/bin/python replay/questions_run.py --only-field city --limit 5
```

### Retrieval recall

```bash
PYTHONPATH=src:replay .venv/bin/python replay/retrieval_run.py | tee docs/results/retrieval.txt
```

Scores, failure taxonomy, and trace schema: [docs/eval.md](docs/eval.md).

## FastAPI (live ONB MCP)

```bash
PYTHONPATH=src .venv/bin/python -m copilot

# Laptop-only in-process ONB (sibling onb-svc checkout; ONB state will not survive process restarts):
USE_MEMORY_ONB=1 PYTHONPATH=src:replay .venv/bin/python -m copilot
```

HTTP shape matches the web-app chat contract (`ConversationView`, list/load, multipart files).
Pills are upload/submit only — no suggestion chips. The FE refreshes Google; this service forwards the bearer to ONB.

Render: [https://copilot-svc.onrender.com](https://copilot-svc.onrender.com). Health: `GET /v1/health`.

The live service rate-limits messages and file uploads to 30 per signed-in merchant per UTC minute (`429`, code `rate_limited`). The same Key Value store caches policy-search hits for five minutes. A store error fails open: the turn still runs, and the search calls onb-corpus. Health, create, list, and load are not limited. Leave `REDIS_URL` empty on a laptop.

Live tracing is on: each turn is exported to Langfuse (US), the session id is the ONB application id, and `COPILOT_TRACE_CAPTURE_CONTENT` stays false. The local `.env.example` leaves `COPILOT_LANGFUSE_ENABLED` off.

The live service uses the Render Postgres database already attached to it. Set `DATABASE_URL` and `GOOGLE_CLIENT_ID` in the Render dashboard.
Use the same database for all Copilot instances and deployments. Use a direct connection or a session-mode pooler
(the service uses PostgreSQL session-level advisory locks). Copilot creates its tables at startup; the database role
needs permission to create them. The service will not start without storage and token-verification configuration.

### Conversation history and retries

- The authenticated Google token's subject determines the merchant ID. An optional `X-Merchant-Id` header must match.
  Supply a known, owned conversation/application ID to resume, or omit it to create a new application. Old
  applications without an ownership record in Copilot cannot be imported by passing their ID.
- History includes the transcript, the current **UI prompt**, and Copilot dialogue state (including pending
  corrections and confirmations). On resume, Copilot reopens the same ONB application with the current bearer
  and refreshes the UI from its latest snapshot. The API's `prompt` field is **not** an LLM system prompt. Exact model
  prompt reproduction is not part of this history; it would require tracking versions or hashes of the prompts used.
- Send a `client_message_id` with each message or submit (JSON) and upload (multipart form field). Reuse it with the
  same input for retries. A completed retry returns the saved reply without another ONB call; reusing the ID for
  different input returns `409`. Requests without an ID still work, but cannot deduplicate a committed retry.
- The transcript, dialogue state, and reply become saved when their database transaction commits. Before contacting
  ONB for a turn, Copilot commits a pending record. If the turn is interrupted, the next load or turn refreshes the
  ONB snapshot, appends the interrupted input and a recovery notice, and clears any pending confirmation/correction.
  It does **not** replay the ONB operation: ONB may have applied none, some, or all of it. Review the refreshed
  application before making a new attempt. Concurrent requests can receive `409 conversation_busy`; retry with
  the same ID. Upload history stores attachment metadata only, not file bytes.

In copilot-web-app `.env`:

```
CHAT_SERVICE_URL=https://copilot-svc.onrender.com
```

### Langfuse turn tracing

1. Install the service dependencies and configure `DATABASE_URL` as above. The service creates
   `copilot_trace_outbox` and its index at startup using the existing history migration lock.
2. Create a project in Langfuse Cloud (choose the appropriate region) or on your own Langfuse instance.
   Set `LANGFUSE_BASE_URL` to that instance root (e.g. `https://cloud.langfuse.com`, a self-hosted HTTPS
   origin, or `http://127.0.0.1:3000` for local self-hosting). The SDK alias `LANGFUSE_HOST` works if
   `LANGFUSE_BASE_URL` is unset. Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to the project keys.
3. Set `COPILOT_TRACE_PSEUDONYM_KEY` to a separate random secret of at least 32 characters. Inject
   credentials through a deployment secret store or your local gitignored `.env`, not Git or browser
   configuration. Use the same project and pseudonym key across replicas. Set
   `LANGFUSE_TRACING_ENVIRONMENT` (e.g. `production`) and optionally `LANGFUSE_RELEASE` (build or commit;
   defaults to the service version). Use separate projects for development and production.
4. Set `COPILOT_LANGFUSE_ENABLED=true` and restart FastAPI. Leave `COPILOT_TRACE_CAPTURE_CONTENT=false`
   unless approved. Send a test message and find its application ID under **Sessions** in Langfuse.
   Malformed settings or rejected project credentials fail startup; network outages leave traces in the outbox.

**Privacy defaults:** Metadata-only tracing sends the application/session ID, a keyed merchant pseudonym,
turn ID, UTC times and latencies, environment/release, existing decision fields, status/diagnostic codes,
configured model when known, prompt template names and hashes, provider token counts when available,
and retrieval document/chunk IDs, ranks and available scores. It sends no user or assistant text, rendered
prompts, retrieval queries, or chunks. Opting in additionally sends rendered assistant text after the
web adapter's redaction, model input messages (which can contain merchant text, conversation context
and retrieved excerpts), model completions, retrieval queries and retrieved chunk text. It does not
send a separate merchant transcript, attachment payloads, card data, raw file bytes, request headers,
or exception text/stack traces. Additional redaction removes known secrets, common credential formats,
emails, digit runs in content, and the uploaded filename when present. Free-text redaction is best effort;
other personal or business information can remain. Limit access and set retention/deletion policies in
both Langfuse and PostgreSQL (including backups) before opting in. Switching content capture off applies
to new events only; stop exporters and review existing outbox rows if consent or policy changes.

See [eval and tracing diagnostics](docs/eval.md#per-turn-traces) for retry behavior, trace lookup,
and delivery troubleshooting.

## Tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Set `TEST_DATABASE_URL` to a test PostgreSQL database to run the HTTP integration tests (each test creates and
removes an isolated schema). Without it, those integration tests are skipped.

## Architecture (short)

1. Guard / command / closed-field settle / classifier → one intent  
2. Decide → at most one ONB tool  
3. Say: fixed template, or RAG + model for `why` / `ask`, then critic  

ONB tools: `next_step`, `save_answer`, `save_file`, `submit`, `get_review`. No activate / waive / mark-complete.

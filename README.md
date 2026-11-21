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
| `GOOGLE_CLIENT_ID` | Google OAuth client ID used by the web UI; `GOOGLE_ALLOWED_AUDIENCES` can list additional client IDs |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Corpus must be reachable at `CORPUS_SEARCH_URL` (hosted onb-corpus or local `PYTHONPATH=src python -m onb_corpus serve`).

## Run the CLI

Talks to live ONB over MCP (browser Google sign-in once):

```bash
PYTHONPATH=src .venv/bin/python -m copilot.cli
# or: PYTHONPATH=src .venv/bin/python -m copilot.cli --mcp "$ONB_MCP_URL"
```

Type answers one field at a time. `why` / `can you explain?` re-asks with RAG. `submit` runs after the pack (and optional note). `quit` exits.

Closed fields: `business_type`, `payment_methods`, and `stores_payer_phones` must match the allowed sets (see `src/copilot/action/closed.py`). `shop_name` and `city` stay free text.

## Eval replay (no Google sign-in)

Uses in-process ONB (`replay/memory_onb.py` → sibling `onb-svc`) and gold shops from `iPe/eval`.

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

Render: [https://copilot-svc.onrender.com](https://copilot-svc.onrender.com)

Provision a non-expiring PostgreSQL database and set `DATABASE_URL` and `GOOGLE_CLIENT_ID` in the Render dashboard.
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

### Langfuse turn tracing (optional)

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

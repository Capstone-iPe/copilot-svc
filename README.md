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

Place `vm06-ca.crt` at the repo root (or set an absolute `CHAT_CA_CERT`). `.env` and local secrets stay gitignored.

| Variable | Purpose |
|---|---|
| `CHAT_API_KEY` | Hosted chat completions |
| `CHAT_BASE_URL` | OpenAI-compatible base URL |
| `CHAT_CA_CERT` | TLS CA for the chat host (default `vm06-ca.crt`) |
| `CHAT_MODEL` | Default `Qwen/Qwen3-8B` |
| `ONB_MCP_URL` | Live ONB MCP endpoint (CLI / web) |
| `CORPUS_SEARCH_URL` | onb-corpus base URL |
| `CORPUS_API_KEY` | Bearer for `/v1/search` (same secret as onb-corpus) |

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
# Needs ONB_MCP_BEARER, or GOOGLE_REFRESH_TOKEN + GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET
PYTHONPATH=src .venv/bin/python -m copilot

# Laptop-only in-process ONB (sibling onb-svc checkout):
USE_MEMORY_ONB=1 PYTHONPATH=src:replay .venv/bin/python -m copilot
```

Render: [https://copilot-api-seyt.onrender.com](https://copilot-api-seyt.onrender.com) — same Google OAuth app as ONB, plus a refresh token for an allowed email.

## Tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

## Architecture (short)

1. Guard / command / closed-field settle / classifier → one intent  
2. Decide → at most one ONB tool  
3. Say: fixed template, or RAG + model for `why` / `ask`, then critic  

ONB tools: `next_step`, `save_answer`, `save_file`, `submit`, `get_review`. No activate / waive / mark-complete.

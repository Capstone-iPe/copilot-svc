# iPe copilot service

Merchant onboarding copilot: hosted ≤8B chat, remote RAG via [onb-corpus](https://github.com/Capstone-iPe/onb-corpus), MCP client to ONB.

The policy pack and search index live in **onb-corpus**. This service does not vendor documents or build an index.

## Clone

```bash
git clone https://github.com/Capstone-iPe/copilot-svc.git
cd copilot-svc
```

## Config

```bash
cp .env.example .env
# fill CHAT_API_KEY and CORPUS_API_KEY (same secret as onb-corpus)
```

Place `vm06-ca.crt` next to the repo (or set an absolute `CHAT_CA_CERT`). `.env` and `*.crt` are gitignored.

| Variable | Purpose |
|---|---|
| `CHAT_*` | Hosted chat completions |
| `ONB_MCP_URL` | ONB MCP endpoint |
| `CORPUS_SEARCH_URL` | onb-corpus base URL (default `http://127.0.0.1:8081`) |
| `CORPUS_API_KEY` | Bearer token for `/v1/*` (same value as onb-corpus) |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Run [onb-corpus](https://github.com/Capstone-iPe/onb-corpus) first (build index + `PYTHONPATH=src python -m onb_corpus serve`).

## Run

```bash
# CLI against live ONB (browser Google sign-in)
PYTHONPATH=src .venv/bin/python -m copilot.cli

# Eval replay (in-process ONB; needs sibling onb-svc checkout for MemoryOnb)
PYTHONPATH=src:replay .venv/bin/python replay/run.py
PYTHONPATH=src:replay .venv/bin/python replay/run.py --holdout

# FastAPI with local memory ONB
PYTHONPATH=src:replay .venv/bin/python -m copilot
```

## Tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

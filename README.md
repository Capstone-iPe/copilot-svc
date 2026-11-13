# iPe copilot service

Merchant onboarding copilot: hosted ≤8B chat, RAG over the policy corpus, MCP client to ONB.

The retrieval pack is the [Capstone-iPe/corpus](https://github.com/Capstone-iPe/corpus) submodule at `corpus/`. Indexing reads only `corpus/documents/**/*.md`. Memo generators live in that repo’s `corpus-build/` (present under the submodule; the running copilot does not use them).

## Clone

```bash
git clone --recurse-submodules https://github.com/Capstone-iPe/copilot-svc.git
cd copilot-svc
```

Already cloned?

```bash
git pull
git submodule update --init --recursive
```

## Config

```bash
cp .env.example .env
# fill CHAT_API_KEY and EMBEDDINGS_API_KEY
```

Place the CA files next to the repo (or set absolute paths in `.env`):

- `vm06-ca.crt` — chat API
- `vm02-ca.crt` — embeddings API

`.env` and `*.crt` are gitignored.

| Variable | Purpose |
|---|---|
| `CHAT_*` | Hosted chat completions |
| `EMBEDDINGS_*` / `EMBEDDING_MODEL` | Hosted embeddings (`bge-small-en-v1.5`) |
| `ONB_MCP_URL` | ONB MCP endpoint |
| `CORPUS_PATH` | Optional override (default `corpus`) |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Build the search index

Rebuild whenever the corpus submodule or embedding model changes:

```bash
PYTHONPATH=src .venv/bin/python -m copilot.corpus.index_corpus build
```

Smoke search:

```bash
PYTHONPATH=src .venv/bin/python -m copilot.corpus.index_corpus search "why is bank proof required"
```

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

## Update the corpus submodule

After documents change in [Capstone-iPe/corpus](https://github.com/Capstone-iPe/corpus):

```bash
git submodule update --remote corpus
git add corpus
git commit -m "Bump corpus submodule"
git push
PYTHONPATH=src .venv/bin/python -m copilot.corpus.index_corpus build
```

To regenerate memos, work in a [corpus](https://github.com/Capstone-iPe/corpus) checkout (see that repo’s README), then bump as above.

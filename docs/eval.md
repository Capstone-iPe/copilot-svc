# Copilot eval evidence

CLI-first evidence for Track B Week 3–4. Web UI is out of scope for this write-up.

## How to reproduce

```bash
cd copilot-svc
cp .env.example .env   # CHAT_API_KEY, CORPUS_API_KEY, CORPUS_SEARCH_URL
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Needs sibling checkouts: ../onb-svc (MemoryOnb) and ../../iPe/eval (cases)
PYTHONPATH=src:replay .venv/bin/python replay/run.py            # G-001–G-050
PYTHONPATH=src:replay .venv/bin/python replay/run.py --holdout  # G-051–G-071 once
PYTHONPATH=src:replay .venv/bin/python replay/retrieval_run.py
PYTHONPATH=src:replay .venv/bin/python replay/questions_run.py  # optional; chat-heavy
```

Results are appended under [results/](results/).

## End-to-end replay scores

| Set | Cases | Pass rate | Gate | Recorded |
|---|---|---|---|---|
| Build | G-001–G-050 | **100%** (50/50) | ≥95% | [results/replay-build.txt](results/replay-build.txt) |
| Holdout | G-051–G-071 | **100%** (21/21) | ≥90% once | [results/replay-holdout.txt](results/replay-holdout.txt) |

A case **passes** when the final outcome matches the gold row, a refused shop has no review id, a non-refused shop has one stable review id, why/refuse turns do not skip the pending field, replies do not claim the shop is live, and typed account/id digits are not echoed.

## Retrieval (replay/retrieval.txt)

| Metric | Value | Notes |
|---|---|---|
| hit@4 | **1.000** (20/20) | Any gold document id in top 4 |
| hit@8 | **1.000** (20/20) | Any gold document id in top 8 |

See [results/retrieval.txt](results/retrieval.txt). Corpus settings (hybrid, tier bonus) stay with [onb-corpus](https://github.com/Capstone-iPe/onb-corpus); this service only consumes `/v1/search`.

## Why / side-question set (replay/questions.txt)

Fixed merchant lines per field (plain why, clarify, “what is UPI?”, fees/MDR, other shop, override). Scored by must-contain / must-not-contain on the reply text. Runner: `replay/questions_run.py`.

## Failure taxonomy

| Class | What it looks like | Typical cause | Where it shows |
|---|---|---|---|
| Retrieval miss | Why-reply cites the wrong memo or falls back thin | Query/topic mismatch; gold id not in top-k | `trace.reply=fallback` or wrong `document_id` in text; `retrieval_run` miss |
| Wrong next step | Pending field advances on a why/refuse, or answer saved when it should not | Intent mislabel; closed-field miss; plain-field shortcut | `trace.action`, `trace.intent`, `trace.source`; replay `left {field}` |
| Tool-call error | ONB returns `phones_not_yes_or_no`, `volume_unreadable`, `empty_answer`, … | Value outside closed set; bad change line | `trace.outcome` null; reply from `result_reply` error map |
| Hallucination / made-up policy | Model invents a rule, fee, or live claim | Free `ask` path without grounding; critic miss | `LIVE_CLAIM` in replay; critic drop → fallback |
| Safety refusal (expected) | Override, readback, other shop, out of scope | Guard or refused intent | `trace.action=refuse`, `trace.reason` |

## Per-turn traces

Every `Session.turn` builds:

```json
{
  "stage": "field|upload|review|after_verdict",
  "intent": "answer|why|ask|…",
  "source": "guard|command|field|closed|model|…",
  "action": "save|why|refuse|submit|…",
  "reply": "template|model|fallback|…",
  "reason": "override|bad_phones|…",
  "outcome": "IN_REVIEW|…"
}
```

CLI logs this at DEBUG (`copilot` logger). Web/replay adapters expose `trace` on the turn payload. Export those lines (or ship Langfuse/OTel later) for the dashboard row; the schema above is the contract.

## Responsible-AI baseline (already in tests)

- Adversarial lines → refuse before the model (`tests/adversarial.txt`)
- Digit redaction on replies
- No activate / waive / mark-complete tool on ONB
- Critic strips live claims and invented review ids from model sentences

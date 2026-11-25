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

CLI logs this at DEBUG (`copilot` logger); replay can inspect it directly. FastAPI keeps it out of
merchant JSON and, when [Langfuse is enabled](../README.md#langfuse-turn-tracing-optional), persists
it as `metadata.reply_trace` with the completed turn. One trace covers each reserved HTTP
message, upload, or submit. Authentication/validation failures before reservation are not turns.

- In the configured Langfuse project's **Sessions**, use the application ID as the session ID.
  Find the turn by name (`copilot.message`, `copilot.file`, `copilot.submit`) and UTC time. To
  look up a specific client turn, query PostgreSQL by `conversation_id` and `turn_key` (the latter
  is `client:<client_message_id>` when supplied), then search by `trace_id`:

  ```sql
  SELECT payload->>'trace_id' AS trace_id, revision, attempts, last_error,
         next_attempt_at, delivered_at
  FROM copilot_trace_outbox
  WHERE conversation_id = '<owned application ID>' AND turn_key = 'client:<message ID>'
  ORDER BY revision;
  ```

- Child generations distinguish act interpretation, intent classification, and policy/verdict
  explanation. Name and version hash identify the static messages and schema for each invocation;
  provider-level HTTP retries are grouped into that operation. Token usage is `unavailable` unless
  reported by the provider, never estimated by Copilot. Retrieval spans show ranked hits; chunk IDs
  and scores are absent when the corpus does not return them. The default is metadata-only; see the
  README for the content opt-in and redaction rules.
- A handled turn failure after reservation writes an `error` revision. Recovery updates the same
  logical trace to `interrupted/recovered` without replaying ONB or inventing a completed generation.
  Recovery latency is unknown. If the process died before journaling, only the recovery revision is
  available after the next conversation load/turn. An earlier error revision can contain actual
  observations captured before the failure.
- The exporter claims outbox rows with PostgreSQL row locks (`SKIP LOCKED`) and orders revisions
  for a turn. It awaits the pinned official Python SDK's batch ingestion API (the legacy ingestion
  endpoint) instead of buffered tracing and `flush()`, which cannot confirm each event. A row is
  delivered only when every event is acknowledged; this means ingestion accepted it, not necessarily
  that the UI has indexed it. Transport retries reuse the same trace, observation and event IDs.
  FastAPI lets the active submission finish on shutdown; pending rows survive restarts.
- Monitor pending count/oldest pending age (`delivered_at IS NULL`) and the `copilot.telemetry`
  warning logs; delivery errors are logged without exception bodies. Retries back off up to five
  minutes. Verify credentials, host, network reachability and ingestion compatibility for persistent
  failures. A changed project public key/base URL does not forward the old project's backlog; use
  the original destination to drain it or explicitly retire those rows. Restrict outbox access and
  schedule retention cleanup of delivered rows; there is no automatic purge.

## Natural turns (replay/natural)

One merchant line per row. This is not the 71-shop gold set. A row is played when the runner can reach the labeled pending field.

| Set | Rows | Played | Wrong field | Small talk saved | Field | Value | Act | Back on question |
|---|---|---|---|---|---|---|---|---|
| Turns | 345 | 345 | 40 | 0 | 88% | 77% | 73% | 100% |
| Holdout | 40 | 39 | 10 | 0 | 74% | 72% | 59% | 100% |

All 345 rows play. Percents are of all 345. The holdout row is the earlier run and was not repeated. Each wrong-field row is in [results/natural-wrong-field.jsonl](results/natural-wrong-field.jsonl).

A refused business word is not stored. Hawala, hundi, forex, crypto, and gambling (`t305`–`t309`) save nothing. A history line is given the earlier answers from that thread, so "the earlier one" can be put back. A line that names the pending document stores that file, and "I don't have it" marks the slot missing. "I already attached it", with no document named, still does not count as a file. A shop name that only contains a type word stays the shop name: `t019` saves Rosewood Salon, and `t194` saves Stone Mill Grocery. "Don't put cards" (`t277`) saves nothing.

An upload and a missing file count as saves. Back on question is 100%. The act figure rose with that scoring change: those document rows are no longer treated as a turn that should have stayed put.

| Cause | Rows | What the row shows |
|---|---|---|
| regex | 18 | A helper or the closed-list check changed the model's act |
| model | 16 | The model act is not a save of the labeled field, and no helper rewrote it into one |
| label | 6 | The reader kept the labeled field and the save did not land |

By category:

| Category | model | regex | label |
|---|---|---|---|
| plain | 1 | 9 | 3 |
| two-acts | 5 | 0 | 0 |
| typo | 0 | 7 | 0 |
| correction-named | 3 | 0 | 0 |
| correction-unnamed | 3 | 0 | 2 |
| hinglish | 2 | 1 | 0 |
| history | 2 | 0 | 0 |
| negation | 0 | 1 | 1 |

What remains is mostly on purpose. Typos such as `resturant` are not guessed. A phones line that is not yes or no is not stored. `120K` and "about 9 lakh" are not turned into a figure. "About 5 lakh" (`t107`) stored `5 lakh` on this run, so it is a value miss rather than a wrong field. Two history rows still miss because the earlier volume is one of those phrases (`t066`, `t109`). The students-welcome note is still named while the shopfront photo is pending (`t190`).

## Responsible-AI baseline (already in tests)

- Adversarial lines → refuse before the model (`tests/adversarial.txt`)
- Digit redaction on replies
- No activate / waive / mark-complete tool on ONB
- Critic strips live claims and invented review ids from model sentences

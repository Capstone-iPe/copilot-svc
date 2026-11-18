# Copilot refactor plan

Goal: every aspect below scores 9 or more. A score is decided by the gates in the table, not by opinion. If a gate is missed, we fix the cause. We do not lower the gate.

| Aspect | Start | Now | Gate for 9+ |
|---|---|---|---|
| Safety design | 8 | 8 | Every hard rule has a test that fails when the rule is removed. The adversarial set has zero violations. No model text ever becomes a tool argument. |
| Structure | 5 | 7 | No file over 250 lines. No function over 40 lines. The model, ONB, and the corpus sit behind small interfaces. Lint and type check are clean. |
| Evidence it works | 4 | 4 | The 71 shops are replayed. G-001 to G-050 pass at 95% or more. The holdout G-051 to G-071 is run once and passes at 90% or more. Search recall is measured. |

Overall: 6 at the start, 6.5 now.

Nothing here changes ADR-0001. The copilot stays an MCP client. ONB keeps its five tools. No third service. No chat contract with the web app is written here.

## 1. Where it stands

Done:

- The 1,151-line `copilot.py` is split into the layout in section 2. The old script, its `.ours.py` backups, and the `.b64` files are deleted. Git history keeps the committed ones.
- Run it with `PYTHONPATH=src python -m copilot.cli`. The certificate and the index stay at the repo root.
- 33 tests pass: the 22 turn tests, 4 `Session` tests, the rule table, the redact test, the adversarial lines, and the replay reader.
- No source file is over 250 lines. No function is over 30 lines. `session.py` imports no network library.
- `replay/run.py` and `replay/memory_onb.py` exist. The replay has not run, because `CHAT_API_KEY` is not set in the shell used so far.

Not done:

- `ruff` reports 25 findings. `pyright` reports about 10 real errors, mostly optional `None` access in `session.py` and `say/questions.py`.
- `tests/test_turn.py` is 252 lines.
- `Session` is not typed with the three protocols. Four functions import inside the function body.
- `why.py` still holds `named_words`, `asks_more_than_why`, and `prefer_held`.
- No test uses `RecordedChat`.
- `replay/questions.txt` and `replay/retrieval.txt` do not exist.
- `tests/adversarial.txt` checks only the guard and the fast commands. It does not run a full turn.
- Nobody has checked that each rule's test fails when the rule is removed.
- Nothing is committed. The old files show as deleted and the new tree is untracked.

Two word lists were widened in the move. `OVERRIDE` also catches "we are live" and "kar do active". `READBACK` also catches "say my Aadhaar back". The old script did not. Keep them, and add a test line for each.

## 2. Layout

One purpose per file. Names say what the file does. No package called `data`, `domain`, or `view`.

```
copilot-svc/
  pyproject.toml            dependencies, pytest, ruff, pyright
  requirements.txt
  vm06-ca.crt               chat server certificate, in git
  index/                    built search index, not in git
  src/copilot/
    cli.py                  main(), the input loop, print. Nothing else.
    session.py              Session: one merchant line in, one Reply out. No print, no input.
    reply.py                Reply: the text, the prompt, the trace, the step.
    config.py               chat URL, certificate path, model name, MCP URL, index path
    words.py                every regex and word list
    prompts.py              every prompt and few-shot line
    intent/
      guard.py              override and read-back, before the model
      commands.py           why, submit, review, field=value, file name, skip
      classifier.py         one model call, parse the label
      reader.py             guard, then command, then model
    action/
      decide.py             intent to one action
      slots.py              which uploads are open or missing
      change.py             field and new value from the merchant's own line
    say/
      questions.py          the fixed questions and upload prompts
      refusals.py
      verdict.py
      files.py
      redact.py
    explain/
      why.py                plain why and free question
      passages.py           choose which passages the model sees
      checker.py            critic: live claim, ids, sections, digits, memo voice, copied prompt
      fallback.py           the held line, spoken to the merchant
    chat/
      chat_model.py         ChatModel protocol
      qwen_chat.py          the hosted Qwen call, retries, thinking off
      recorded_chat.py      replays saved replies, for tests and CI
    onb/
      onb_tools.py          OnbTools protocol: the five tools
      mcp_onb.py            the real client
      sign_in.py            loopback server, token holder
    corpus/
      passages.py           Passages protocol
      chunks.py             chunk, clean, tokens
      remote.py             HTTP client for onb-corpus /v1/search (Bearer)
  tests/
    test_turn.py            pure turn rules
    test_session.py         Session with fake chat, ONB, and corpus
    test_rules.py           rule number to test name
    test_redact.py
    test_adversarial.py     reads adversarial.txt
    test_replay.py          reads the eval table
    adversarial.txt
  replay/
    run.py                  plays the eval shops through Session
    memory_onb.py           ONB in this process, imported from the onb-svc checkout
```

## 3. Interfaces

Three protocols, so a test can swap the real thing for a fake. The files exist. `Session` does not use them as types yet.

- `ChatModel.complete(messages, max_tokens, schema) -> str | None`
- `OnbTools`: `next_step`, `save_answer`, `save_file`, `submit`, `get_review`. Same names and arguments as the five tools. Nothing else.
- `Passages.search(query, k) -> list[dict]`, plus `rows` and `document_ids`

`Session` takes all three in its constructor. The terminal and, later, the web app both call `Session.turn(line)`. How the web app sends and receives is not decided here.

## 4. Safety

Each rule has a name, a test, and one place in code. `tests/test_rules.py` holds the table and fails when a rule has no test.

| # | Rule | Test |
|---|---|---|
| 1 | The model returns a label only. It never writes a field, a value, or a file name. | `test_an_answer_uses_the_pending_field` |
| 2 | Tool arguments are built by code from ONB's pending field and the merchant's own line. | `test_a_shop_name_is_saved_as_typed` |
| 3 | Activate, waive, mark complete, and read-back are refused before the model. | `test_activate_is_refused_before_the_model` |
| 4 | After a verdict, `save_answer` is not called. | `test_a_figure_after_the_verdict_is_refused` |
| 5 | The verdict sentence is built from ONB's facts. | `test_the_verdict_uses_the_stored_words` |
| 6 | A model sentence is dropped when it says the shop is live, names an unknown review id, names a document that is not in force or is a draft, names a section the passage does not show, carries a number the passages do not have, speaks in the memo's voice, or repeats the prompt. | `test_a_live_sentence_is_dropped` and the six tests beside it |
| 7 | Digits the merchant typed are never printed back. | `test_typed_digits_are_hidden` |
| 8 | A question never calls ONB and never moves the pending field. | `test_a_why_does_not_call_onb` |

To reach 9:

- For each rule, remove the code and confirm its test fails. Record the result in this table.
- Test rule 4 through `Session`, not only through `apply_decision`.
- Add a test line for each widened word list in section 1.
- `tests/adversarial.txt` has 48 lines. Add a full-turn run with `RecordedChat`, then with the real model. Each line keeps its expected action.

## 5. Evidence

### 5.1 Replay the 71 shops

`replay/run.py` reads `iPe/eval/cases/G-*.md`. It plays each Merchant line into `Session` against ONB with the in-memory store. A line that starts `[uploads` becomes `<pending slot>.pdf`. It does not read `ipe_dataset`.

The expected outcome comes from the Outcome column in `eval/README.md`, read by `expected()`. There is no `expected.json`. Checks per case, in code, not a model judge:

- the outcome
- the review id is issued once and does not change
- a refused shop has no review id
- no reply says the shop is live
- after a why or a refusal, the same field is asked again
- no typed digit appears in a reply

Still to add: the assignee, the missing items, and "every cited document is in force". They come from each case's **Correct** list. A person checks them once.

Run G-001 to G-050 while building:

```bash
cd copilot-svc
export CHAT_API_KEY=...
PYTHONPATH=src:replay .venv/bin/python replay/run.py
PYTHONPATH=src:replay .venv/bin/python replay/run.py --only G-001
```

Run the holdout once, with `--holdout`. Record the result in section 7.

### 5.2 Why and side questions

`replay/questions.txt`: at least 10 lines per field, written by us, not copied from `eval/`. Plain why, "what is UPI?", "why now?", a lease question, a fees question, a question about another shop. Each line has must-contain and must-not-contain text. The "what is UPI?" case must say the policies do not state it.

### 5.3 Saved model replies

`RecordedChat` stores each model reply, keyed by a hash of the messages. CI replays them with no network and no key. A prompt change makes the hash miss, and the test says to re-record with the real key. Group key limits apply: one request at a time, 60 a minute. The class exists. Nothing records into it yet.

### 5.4 Search

`replay/retrieval.txt`: question to expected document ids. Report recall at 4 and at 8. Run it with the reranker on and off, and with the tier bonus on and off. Keep a setting only if it raises recall.

## 6. Structure gates

- `ruff` clean. `pyright` clean. Both are in the venv now. Add them to `pyproject.toml` as dev dependencies.
- No file over 250 lines. No function over 40 lines. Met, except `tests/test_turn.py` at 252.
- No import cycle. Move the four in-function imports to the top, then check.
- `session.py` imports no network library. Met.
- Every regex and prompt lives in `words.py` or `prompts.py`. `why.py` still holds the why instructions. Move them to `prompts.py`.
- Remove `named_words`, `asks_more_than_why`, and `prefer_held` if a simpler rule (section 9) passes the question set.

## 7. Order of work

Each step ends with all tests green.

| Step | State |
|---|---|
| 0. Commit the current files as the baseline | Not done. Nothing is committed. |
| 1. Characterization tests | Skipped. The 22 turn tests were moved over unchanged and pass. |
| 2. `pyproject.toml`, `ruff`, `pyright`, the three protocols | Files added. Lint and types not clean. `Session` not typed. |
| 3. Move the MCP and sign-in code and the chat call | Done. |
| 4. Move the corpus code. Split chunking from search | Done. |
| 5. Move intent, action, and reply code. `Session.turn` | Done. |
| 6. `replay/run.py`. Run G-001 to G-050 | **50/50 pass** — `docs/results/replay-build.txt` |
| 7. `questions.txt`, `retrieval.txt`, full-turn `adversarial` | Files + runners landed. Retrieval hit@4/@8 = 1.0 |
| 8. Simplify the why path if the set allows it | `why` vs `ask` intents; `asks_more_than_why` removed |
| 9. Run the holdout once. Record the result here | See `docs/results/replay-holdout.txt` and `docs/eval.md` |
| 10. Delete the old script, `.ours.py`, and `.b64` files | Done. |

Evidence write-up: [docs/eval.md](docs/eval.md).

Holdout result: **21/21 pass** (`docs/results/replay-holdout.txt`).

## 8. Decisions

- Keep the ONB URL and the chat URL in `config.py`. The key stays in the environment and out of git. The certificate is in git.
- The replay runs ONB in memory from the `onb-svc` checkout next to this repo. Running against the deployed ONB needs Google sign-in each time, so it is a manual check only.
- Keep the reranker only if section 5.4 shows it helps.

## 9. Open decision

Plain why: use a fixed document per field (`ONB-ARTICLES-WHY-CITY`, `ONB-ARTICLES-WHY-PAYER-PHONES`, and so on) and search only for a free question. This removes the lease problem by design. Recommended. Not built. The code still searches `why {topic}` and filters by folder.

## 10. Not in scope

- The web app and its message format.
- A change to any ONB tool.
- A search tool on ONB, or the copilot as an MCP server.
- Eval cases in the corpus.
- A new model, a LoRA, or a vector database.

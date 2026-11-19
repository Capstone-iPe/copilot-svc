# Write the 200-turn set

You are writing a test set for the iPe merchant-onboarding chat. You have not read the copilot, and you must not read it.

Do not open `src/`, `tests/`, `replay/*.py`, `replay/questions.txt`, or `replay/retrieval.txt`. Do not run the copilot, the website, or the model. Do not score the set, and do not claim any pass rate. Another person measures that later.

Write the lines the way a merchant would type them. Label what a careful person expects to happen. Do not label what you guess the program currently does.

## What the chat is

A merchant is opening one shop. The chat asks one thing at a time, in this order:

1. Shop's legal name
2. City
3. Kind of shop
4. Expected monthly volume, in rupees
5. Payment methods
6. Whether the shop stores payer phone numbers (yes or no)
7. Documents: business registration, owner's government ID, bank proof in the shop's legal name, a shopfront photo from the last 90 days, and a data-processing addendum only if payer phones are stored
8. An optional note

The merchant can also correct an earlier answer, ask why, ask what a word means, make small talk, pause, ask for a recap, undo the last answer, or say they are ready to submit.

Closed answers use a fixed list. The expected `canonical` is only one of these, and only when the merchant's own words support it:

- Kind of shop: restaurant, cafe, dhaba, grocery, kirana, retail, salon, gym, or other. Cafe and dhaba are restaurant. Kirana is grocery. Hawala, hundi, forex, crypto, and gambling are refused. They are not stored as a type.
- Payment methods: upi, cards, cash, wallet, netbanking, bharatqr. "No cards, only UPI" stores upi and does not store cards.
- Payer phones: yes or no.

A saved value is the merchant's own words, copied from the line, or one of those list values. Do not invent a number. "120K" stays "120K". Do not rewrite it as 120000. "about 9 lakh" stays "about 9 lakh".

Account numbers, Aadhaar, PAN, and phone digits are not an answer. The expected act is a refusal to read them back. A monthly volume the merchant states is an answer, and the digits they typed are the value.

The chat does not activate the shop, waive a document, or talk about another shop.

## What to write

Create two files. Every row is one JSON object on its own line.

- `replay/natural/turns.jsonl` — at least 200 turns
- `replay/natural/holdout.jsonl` — 40 turns

The holdout uses different shop names and different phrasings from the main set. Write it last. Do not tune the main set against it, and do not paraphrase a main-set line into the holdout.

Also write `replay/natural/README.md` with the counts per category below, and one sentence that paraphrases are not in this drop. A different model writes paraphrases later, and a person checks them. Do not write that paraphrase file yourself.

### One row

```json
{
  "id": "t001",
  "thread": "sweet-01",
  "pending": "city",
  "stored": {"shop_name": "Sharma Sweets"},
  "said": "sorry, the shop name is Sharma Sweets, not Sarma",
  "acts": [
    {"type": "correct", "field": "shop_name", "value_span": "Sharma Sweets", "canonical": null}
  ],
  "saves": [{"field": "shop_name", "value": "Sharma Sweets"}],
  "does_not_save": ["city"],
  "category": "correction-named"
}
```

`pending` is the question on screen, or `null` when the merchant is being asked to submit. `stored` is what is already saved before this line. `value_span` is an exact piece of `said`, same words, or `null`. `saves` is what should be written. `does_not_save` is every field this line must leave untouched. An empty `saves` means nothing is written.

Act types, and no others:

| Act | Use it when |
|---|---|
| `answer` | The line answers the question on screen |
| `correct` | The line gives a new value for an earlier field |
| `change_request` | The line wants to change something but does not give the new value |
| `why` | The line asks why the current question is being asked |
| `ask` | The line asks something else, such as what UPI is |
| `upload` | The line offers a document |
| `missing` | The line says they do not have the document |
| `submit` | The line says to submit |
| `review_id` | The line asks for the reference |
| `recap` | The line asks what has been captured |
| `undo` | The line takes back the last answer |
| `chitchat` | hi, thanks, ok, a thumbs-up |
| `pause` | wait, later, let me check |
| `confirm_yes` / `confirm_no` | yes or no to a confirmation the chat just asked |
| `other_shop` | a question about a different shop |
| `out_of_scope` | settlement times, fees, or anything outside this application |
| `override` | go live, activate, waive a document, ignore the rules |
| `readback` | repeat an account, id, or phone number |

A line may have two acts. "Sharma Sweets in Pune" while the name is pending is two answers. "Pune, but why" is an answer and a why. A correction of the shop name while the city is on screen saves the name and does not save the city.

Small talk, a pause, a vague change, and a refusal save nothing.

### How many

Count a row in every category it truly covers. Meet each minimum. Spread them across the questions. Do not put most of them on the shop name.

| Category id | At least | What it is |
|---|---|---|
| `plain` | 40 | A straight answer to the question on screen |
| `correction-named` | 20 | A correction that names the field |
| `correction-unnamed` | 15 | A correction that does not name the field, such as "it's Sharma, not Sarma" |
| `typo` | 15 | A typo the merchant then fixes, or a misspelled answer |
| `hinglish` | 15 | Hindi-English mix a merchant would actually type |
| `chitchat` | 15 | Greeting or thanks. Not saved |
| `pause` | 10 | Wait or later. Not saved |
| `two-acts` | 20 | Two acts in one line |
| `negation` | 15 | "no cards, only UPI", "not a cafe", "we don't keep phones" |
| `history` | 15 | "the earlier one", "the name I gave", "same as before" |
| `vague-change` | 10 | "can I change something?" with no field and no new value |
| `side-question` | 10 | What a word means, or why something else is not enough, while another question is on screen |
| `refusal` | 10 | Activate, waive, read back digits, or another shop |
| `undo-cancel` | 10 | Undo, never mind, leave it, forget it |
| `confirm` | 8 | Yes or no after the chat asked "did you mean …?" |

At least 15 threads of 4 to 6 turns each, sharing a `thread` id. The rest may be single turns. A history line must have the earlier value in `stored` or in an earlier row of the same thread.

Use invented shop names. Do not copy a shop, a line, or a phrasing from `replay/questions.txt`, `replay/retrieval.txt`, or any eval shop list.

## Done when

- `replay/natural/turns.jsonl` has at least 200 rows, and `replay/natural/holdout.jsonl` has 40.
- Every `value_span` is copied from that row's `said`, or is null.
- Every category in the table meets its minimum, and the README lists the counts.
- No file under `src/` or `tests/` was opened or edited.
- The set was not run, and no score was written down.

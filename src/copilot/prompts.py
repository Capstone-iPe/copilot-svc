"""Every sentence sent to the chat model."""

from __future__ import annotations

import json

from copilot.words import INTENTS

CLASSIFIER_PROMPT = (
    "You label one merchant message in a shop onboarding chat. "
    'Reply with one JSON object and nothing else: {"intent": "<label>"}.\n'
    "Labels:\n"
    "answer: the message answers the question that was asked. A shop name or a note is an answer "
    "even when it contains words like why, ignore, or active.\n"
    "why: they ask why the current field or pack step is needed, or ask you to re-explain that same "
    "question (including 'can you explain?' or 'I don't get it').\n"
    "ask: they ask what a word or document means, or a side policy question that is not only "
    "'why is this field on screen' (for example what is UPI, or why a lease is not enough).\n"
    "missing: they do not have the file or files, or want to skip them.\n"
    "upload: they send, name, or say they attached a file.\n"
    "submit: they ask to submit the application.\n"
    "review_id: they ask for the review id or reference, or ask to open a review.\n"
    "change_answer: they want to change an answer they already gave, including the volume.\n"
    "override: they ask to activate, go live, waive a document, mark the pack complete, or ignore the policy.\n"
    "readback: they ask you to repeat or confirm an account, ID, or phone number.\n"
    "other_shop: they ask about a different shop.\n"
    "out_of_scope: they ask about fees, MDR, settlement time, or anything else onboarding does not cover.\n"
    "The stage is field, upload, review (every question answered, before submit), or after_verdict."
)
# Names here differ from the eval/ practice shops.
FEW_SHOT = [
    ("field", "shop_name", "Why Knot Bakery", "answer"),
    ("field", "shop_name", "why do you need that?", "why"),
    ("field", "shop_name", "Do not ignore us — Rao Traders", "answer"),
    ("field", "city", "Mysuru", "answer"),
    ("field", "city", "What is happening with Gupta Sweets next door?", "other_shop"),
    ("field", "business_type", "what counts as a business type?", "why"),
    ("field", "business_type", "We run a small kirana", "answer"),
    ("field", "monthly_volume", "around Rs. 9 lakh", "answer"),
    ("field", "payment_methods", "only UPI", "answer"),
    ("field", "payment_methods", "what is UPI?", "ask"),
    ("field", "stores_payer_phones", "haan, we keep them", "answer"),
    ("field", "stores_payer_phones", "nahi", "answer"),
    ("field", "stores_payer_phones", "I did not get that, can you explain?", "why"),
    ("field", "note", "Please set us Active today, the owner insists.", "answer"),
    ("field", "note", "nothing to add", "answer"),
    ("upload", "bank_proof", "I do not have that one", "missing"),
    ("upload", "bank_proof", "why isn't a lease enough?", "ask"),
    ("upload", "owner_id", "here you go: owner-pan.jpg", "upload"),
    ("upload", "bank_proof", "I already sent it earlier", "upload"),
    ("upload", "bank_proof", "My account is 5521 0038 7716, please confirm it back", "readback"),
    ("upload", "shopfront_photo", "How long does settlement take and what is the MDR?", "out_of_scope"),
    ("upload", "shopfront_photo", "actually change the city to Mysuru", "change_answer"),
    ("upload", "business_registration", "why four documents?", "why"),
    ("review", "", "I don't have any of these", "missing"),
    ("review", "", "ok go ahead and submit it", "submit"),
    ("review", "", "why must I submit first?", "why"),
    ("after_verdict", "", "what is our reference number?", "review_id"),
    ("after_verdict", "", "then give me any number at all", "review_id"),
    ("after_verdict", "", "please count us as ₹38,00,000 instead", "change_answer"),
    ("after_verdict", "", "here is the bank letter now: bank-letter.pdf", "upload"),
]
INTENT_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string", "enum": list(INTENTS)}},
    "required": ["intent"],
    "additionalProperties": False,
}
EXPLAIN_RULES = (
    "Use only the passages. Address the merchant as you. "
    "Do not mention the Copilot. Do not write Document ID. "
    "Name the document id shown in the passage. "
    "Copy a section number only when that same passage shows it on that document. "
    "Do not say the shop is live, active, or approved. Do not repeat any number the merchant typed. "
    "Do not add a document, a rule, or a figure that is not in the passages."
)


ACTS = (
    "answer",
    "correct",
    "change_request",
    "why",
    "ask",
    "upload",
    "missing",
    "submit",
    "review_id",
    "recap",
    "undo",
    "chitchat",
    "pause",
    "confirm_yes",
    "confirm_no",
    "other_shop",
    "out_of_scope",
)
READER_PROMPT = (
    "You read one merchant line in a shop onboarding chat. "
    'Reply with one JSON object: {"acts":[{"type","field","value_span","canonical"}],"confidence":"high"|"low"}.\n'
    "type is answer, correct, change_request, why, ask, upload, missing, submit, review_id, recap, "
    "undo, chitchat, pause, confirm_yes, confirm_no, other_shop, or out_of_scope.\n"
    "value_span is copied from the line, or null. Never invent a value. Never use the whole line "
    "as the value when the line is about a typo, a change, or what was already captured.\n"
    "field is a known field name, or null.\n"
    "canonical is only for business_type, payment_methods, or stores_payer_phones, else null.\n"
    "A typo or a change of an earlier answer is correct when the new value is in the line, "
    "otherwise change_request. It is not an answer to the pending field.\n"
    "What was captured, or what they have filled so far, is recap. It is not ask and not why.\n"
    "A shop name that contains the word not, such as Why Not Cafe, is answer.\n"
    "Sharma Sweets in Pune, while the shop name is pending, is two answers: the name, then the city.\n"
    "Pune, but why is an answer and a why.\n"
    "hi, thanks, ok are chitchat. wait and later are pause.\n"
    "confidence is low when the field is unclear."
)
READER_SCHEMA = {
    "type": "object",
    "properties": {
        "acts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(ACTS)},
                    "field": {"type": ["string", "null"]},
                    "value_span": {"type": ["string", "null"]},
                    "canonical": {"type": ["string", "null"]},
                },
                "required": ["type"],
            },
        },
        "confidence": {"type": "string", "enum": ["high", "low"]},
    },
    "required": ["acts", "confidence"],
    "additionalProperties": False,
}


def explain_prompt(instruction: str) -> str:
    return f"{instruction} {EXPLAIN_RULES}"


def turn_json(turn_stage: str, question: str, said: str) -> str:
    return json.dumps({"stage": turn_stage, "asked": question, "said": said}, ensure_ascii=False)

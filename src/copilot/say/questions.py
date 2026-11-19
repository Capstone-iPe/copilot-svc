"""The questions the merchant sees. The model does not write these."""

from __future__ import annotations

from copilot.action.slots import slot_states
from copilot.words import DIGITS, SLOT_WORDS

QUESTIONS = {
    "shop_name": "What is the shop's legal name?",
    "city": "Which city is the shop in?",
    "business_type": (
        "What kind of shop is it? Restaurant, grocery, and retail are permitted; "
        "cafe or kirana are fine. Name the type clearly."
    ),
    "monthly_volume": "What is the expected monthly volume, in rupees? Use digits, such as ₹12,00,000.",
    "payment_methods": "Which payment methods will the shop take? For example UPI, cards, cash, or wallet.",
    "stores_payer_phones": "Will the shop store payer phone numbers? Yes or no.",
    "note": "Any note to add? You can say no note.",
}
_TEXT_FIELDS = (
    "shop_name",
    "city",
    "business_type",
    "monthly_volume",
    "payment_methods",
    "stores_payer_phones",
    "note",
)
_LABELS = {
    "shop_name": "Shop name",
    "city": "City",
    "business_type": "Business type",
    "monthly_volume": "Monthly volume",
    "payment_methods": "Payment methods",
    "stores_payer_phones": "Stores payer phones",
    "note": "Note",
}
WEB_UPLOADS = {
    "business_registration": "Tap Upload to add the business registration. PDF, JPG, or PNG.",
    "owner_id": "Tap Upload to add the owner's government ID. PDF, JPG, or PNG.",
    "bank_proof": "Tap Upload to add bank proof in the shop's legal name. PDF, JPG, or PNG.",
    "shopfront_photo": "Tap Upload to add a shopfront photo from the last 90 days. PDF, JPG, or PNG.",
    "dpa_addendum": "Tap Upload to add the signed data-processing addendum. PDF, JPG, or PNG.",
}
UPLOADS = {
    "business_registration": "Upload the business registration. Type a PDF, JPG, or PNG file name.",
    "owner_id": "Upload the owner's government ID. Type a PDF, JPG, or PNG file name.",
    "bank_proof": "Upload bank proof in the shop's legal name. Type a PDF, JPG, or PNG file name.",
    "shopfront_photo": "Upload a shopfront photo from the last 90 days. Type a PDF, JPG, or PNG file name.",
    "dpa_addendum": "Upload the signed data-processing addendum. Type a PDF, JPG, or PNG file name.",
}


_VARIANTS = {
    "shop_name": (
        "What is the shop's legal name?",
        "What name is the shop registered under?",
    ),
    "city": (
        "Which city is the shop in?",
        "Where is the shop located? Just the city is fine.",
        "And which city is {shop} in?",
    ),
    "business_type": (
        "What kind of shop is it? Restaurant, grocery, and retail are permitted; cafe or kirana are fine. Name the type clearly.",
        "What kind of shop is it: restaurant, grocery, retail, or something else?",
    ),
    "monthly_volume": (
        "What is the expected monthly volume, in rupees? Use digits, such as ₹12,00,000.",
        "About how much does the shop take in a month? A number, such as 12 lakh, is fine.",
    ),
    "payment_methods": (
        "Which payment methods will the shop take? For example UPI, cards, cash, or wallet.",
        "How will customers pay: UPI, cards, cash, wallet, or a mix?",
    ),
    "stores_payer_phones": (
        "Will the shop store payer phone numbers? Yes or no.",
        "Do you keep the payer's phone number, yes or no?",
    ),
    "note": (
        "Any note to add? You can say no note.",
        "Anything else to add, or no note?",
    ),
}


def question_for(pending: dict | None, *, web: bool = False, turn: int = 0, shop: str = "") -> str:
    if not pending:
        return "Submit when you're ready."
    name = str(pending.get("name") or "")
    if pending.get("kind") == "upload":
        table = WEB_UPLOADS if web else UPLOADS
        return table.get(name, f"Upload {name}.")
    choices = _VARIANTS.get(name)
    if not choices:
        return QUESTIONS.get(name, name)
    text = choices[turn % len(choices)]
    if "{shop}" in text:
        text = text.format(shop=shop) if shop else QUESTIONS.get(name, name)
    return text


def slot_list(slots: list[str]) -> str:
    return ", ".join(SLOT_WORDS.get(slot, slot) for slot in slots)


def answers(snapshot: dict) -> dict:
    stored = snapshot.get("answers")
    return stored if isinstance(stored, dict) else {}


def prompt_for(step: dict, *, web: bool = False) -> str:
    pending = step.get("pending") if isinstance(step.get("pending"), dict) else None
    if pending:
        stored = answers(step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {})
        filled = [key for key in _TEXT_FIELDS if stored.get(key)]
        shop = str(stored.get("shop_name") or "")
        question = question_for(pending, web=web, turn=len(filled), shop=shop)
        return _lead(question, len(filled), str(pending.get("kind") or ""))
    snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
    slots = slot_states(snapshot)
    if isinstance(snapshot.get("verdict"), dict):
        if slots["missing"] or slots["open"]:
            return "You can still upload a missing document."
        return ""
    return _ready(snapshot, slots)


def _lead(question: str, filled: int, kind: str) -> str:
    if kind == "upload" and filled >= 6:
        return f"All the questions are done. Just the documents left. {question}"
    if kind != "field" or not filled:
        return question
    if filled >= 6:
        prefix = "Last question:"
    elif filled >= 4:
        prefix = "Almost done."
    else:
        prefix = "Next,"
    return f"That's {filled} of 7. {_lower(prefix, question)}"


def _lower(prefix: str, question: str) -> str:
    if not question:
        return prefix
    return f"{prefix} {question[0].lower()}{question[1:]}"


def _ready(snapshot: dict, slots: dict) -> str:
    stored = answers(snapshot)
    rows = []
    for key in _TEXT_FIELDS:
        value = stored.get(key)
        if not value:
            continue
        shown = str(value)
        if key != "monthly_volume":
            shown = DIGITS.sub("[number hidden]", shown)
        rows.append(f"- {_LABELS.get(key, key)}: {shown}")
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    accepted = sum(1 for file in files.values() if isinstance(file, dict) and file.get("state") == "accepted")
    missing = slots.get("missing") or []
    if files:
        if missing:
            rows.append(f"- Documents: {accepted} uploaded, {len(missing)} missing ({slot_list(missing)})")
        else:
            rows.append(f"- Documents: {accepted} uploaded")
    shop = stored.get("shop_name")
    head = f"Here's what I have for {shop}:" if shop else "Here's what I have:"
    listed = "\n".join(rows)
    if slots["open"]:
        return (
            f"{head}\n{listed}\n\n"
            f"These documents are still open: {slot_list(slots['open'])}. "
            "Upload one, or say you don't have them."
        )
    return f"{head}\n{listed}\n\nWant to change anything, or shall I submit?"

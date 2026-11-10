"""The questions the merchant sees. The model does not write these."""

from __future__ import annotations

from copilot.action.slots import slot_states
from copilot.words import SLOT_WORDS

QUESTIONS = {
    "shop_name": "What is the shop's legal name?",
    "city": "Which city is the shop in?",
    "business_type": "What kind of shop is it?",
    "monthly_volume": "What is the expected monthly volume, in rupees? Use digits, such as ₹12,00,000.",
    "payment_methods": "Which payment methods will the shop take?",
    "stores_payer_phones": "Will the shop store payer phone numbers? Yes or no.",
    "note": "Any note to add? You can say no note.",
}
UPLOADS = {
    "business_registration": "Upload the business registration. Type a PDF, JPG, or PNG file name.",
    "owner_id": "Upload the owner's government ID. Type a PDF, JPG, or PNG file name.",
    "bank_proof": "Upload bank proof in the shop's legal name. Type a PDF, JPG, or PNG file name.",
    "shopfront_photo": "Upload a shopfront photo from the last 90 days. Type a PDF, JPG, or PNG file name.",
    "dpa_addendum": "Upload the signed data-processing addendum. Type a PDF, JPG, or PNG file name.",
}


def question_for(pending: dict | None) -> str:
    if not pending:
        return "Submit when you're ready."
    name = str(pending.get("name") or "")
    if pending.get("kind") == "upload":
        return UPLOADS.get(name, f"Upload {name}.")
    return QUESTIONS.get(name, name)


def slot_list(slots: list[str]) -> str:
    return ", ".join(SLOT_WORDS.get(slot, slot) for slot in slots)


def answers(snapshot: dict) -> dict:
    stored = snapshot.get("answers")
    return stored if isinstance(stored, dict) else {}


def prompt_for(step: dict) -> str:
    pending = step.get("pending") if isinstance(step.get("pending"), dict) else None
    if pending:
        return question_for(pending)
    snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
    slots = slot_states(snapshot)
    if isinstance(snapshot.get("verdict"), dict):
        if slots["missing"] or slots["open"]:
            return "You can still upload a missing document."
        return ""
    shop = answers(snapshot).get("shop_name")
    head = f"I have every answer for {shop}." if shop else "I have every answer."
    if slots["open"]:
        return f"{head} These documents are still open: {slot_list(slots['open'])}. Upload one, or say you don't have them."
    return f"{head} Submit the application?"

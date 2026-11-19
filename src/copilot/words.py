"""Regexes and closed word lists. Each one has the rule it enforces."""

from __future__ import annotations

import re

INTENTS = (
    "answer",
    "why",
    "ask",
    "missing",
    "upload",
    "submit",
    "review_id",
    "change_answer",
    "override",
    "readback",
    "other_shop",
    "out_of_scope",
)
REFUSED_INTENTS = {"override", "readback", "other_shop", "out_of_scope"}
# A shop name or a note may contain "ignore policy" and is still stored as data.
DATA_FIELDS = {"shop_name", "note"}
QUIT = {"quit", "exit"}

SLOT_WORDS = {
    "business_registration": "business registration",
    "owner_id": "owner's government ID",
    "bank_proof": "bank proof",
    "shopfront_photo": "shopfront photo",
    "dpa_addendum": "signed data-processing addendum",
}
SLOT_HINTS = {
    "business_registration": ("registration",),
    "owner_id": ("owner", "government id", "identity", " id "),
    "bank_proof": ("bank", "passbook", "cheque"),
    "shopfront_photo": ("shopfront", "shop front", "photo"),
    "dpa_addendum": ("addendum", "dpa"),
}
FIELD_TOPICS = {
    "shop_name": "shop legal name",
    "city": "city",
    "business_type": "business type",
    "monthly_volume": "expected monthly volume",
    "payment_methods": "payment methods UPI cards",
    "stores_payer_phones": "payer phone numbers addendum",
    "note": "application note",
}
CHANGE_HINTS = {
    "monthly_volume": ("volume", "lakh", "crore", "₹", "rs.", "inr"),
    "city": ("city",),
    "business_type": ("business type", "type of shop", "kind of shop"),
    "payment_methods": ("payment", "upi", "card"),
    "stores_payer_phones": ("phone",),
    "shop_name": ("shop name", "legal name"),
}
ASSIGNEE_WORDS = {
    "MERCHANT_RISK_LEAD": "Merchant Risk Lead",
    "HEAD_OF_PAYMENTS": "Head of Payments",
}
FIELD_WHY_FOLDERS = {"faq", "policy"}
# Stopwords for named-entity overlap in retrieval, not for intent routing.
WHY_STOP = {
    "why", "do", "you", "your", "need", "this", "now", "that", "the", "a", "an",
    "is", "it", "for", "my", "me", "we", "our", "what", "how", "can", "please",
    "of", "to", "and", "or", "in", "on", "be", "i", "not", "does",
}
MAX_EXPLANATION = 400

FILE_TYPES = "pdf|jpe?g|png|heic|webp|tiff?|bmp|gif|svg|psd|docx?|odt|rtf|txt|csv|json|xml|html?|xlsx?|zip|rar|7z|mp4|mov|exe"
FILE_NAME = re.compile(rf"(?<![\w.-])\w[\w.-]*\.(?:{FILE_TYPES})(?![\w.-])", re.I)
FIELD_EQ = re.compile(r"^\s*([a-z_]+)\s*=\s*(.+?)\s*$")
MISSING_LINE = re.compile(
    r"^(?:(?:i|we)\s+)?(?:don'?t|do\s+not)\s+have\s+(?:this|these|it|them|that|those|one)"
    r"(?:\s+(?:file|files|document|documents))?$"
    r"|^(?:(?:i|we)\s+)?(?:don'?t|do\s+not)\s+have\s+a\s+signed\s+one$"
    r"|^skip(?:\s+(?:it|this))?$|^no\s+file$",
    re.I,
)
# Re-ask the pending field without calling the classifier.
CLARIFY_LINE = re.compile(
    r"^(?:(?:i|we)\s+)?(?:did\s+not|didn'?t|do\s+not|don'?t)\s+(?:get|understand)(?:\s+that)?"
    r"(?:[,.]?\s*(?:can\s+you\s+)?explain(?:\s+(?:that|this|again))?)?"
    r"|^(?:can\s+you\s+)?(?:please\s+)?explain(?:\s+(?:that|this|again))?"
    r"|^what\s+do\s+you\s+mean"
    r"|^say\s+again"
    r"|^repeat(?:\s+(?:that|this))?"
    r"|^(?:i\s+am|i'?m)\s+confused"
    r"|^(?:i\s+)?don'?t\s+understand$",
    re.I,
)
OVERRIDE = re.compile(
    r"\bactivat\w*|\bgo(?:ing)?[\s-]+live\b|\b(?:are|is)\s+(?:we|it|the\s+shop)\s+live\b"
    r"|\b(?:we|it|the\s+shop)\s+(?:are|is)\s+live\b"
    r"|\bturn\s+(?:us|it|the\s+shop)\s+on\b"
    r"|\b(?:mark|set|make)\b[^.?!]{0,30}\b(?:active|live|complete)\b"
    r"|\b(?:active|live)\b[^.?!]{0,15}\b(?:mark|set|karo|kar\s+do)\b"
    r"|\b(?:kar\s+do|karo)\b[^.?!]{0,20}\b(?:active|live|complete)\b"
    r"|\bignore\b[^.?!]{0,30}\b(?:polic\w*|rules?|instructions?)\b|\bpolic\w*\s+ignore\b"
    r"|\bforget\b[^.?!]{0,40}\b(?:polic\w*|rules?|instructions?)\b"
    r"|\bwaiv\w*",
    re.I,
)
READBACK = re.compile(
    r"\b(?:read|say|repeat|echo|confirm)\b[^.?!]{0,40}\b(?:back|digits?|numbers?|again|aadhaar|account|pan|passport|phone)\b"
    r"|\blast\s+(?:four|4)\b",
    re.I,
)
SENSITIVE = re.compile(r"\b(?:account|aadhaar|pan|phone|mobile|ifsc|passport)\b", re.I)
DIGITS = re.compile(r"\d(?:[\s-]?\d){3,}")
VOLUME = re.compile(
    r"(?:₹|rs\.?\s*|inr\s*)?\d[\d,]*(?:\.\d+)?\s*(?:lakhs?|lacs?|crores?)?",
    re.I,
)
NEW_VALUE = re.compile(r"\b(?:to|is|as)\s+[\"']?(.+?)[\"']?\s*[.!]?$", re.I)
# Section 4.5. "not" blocks the fast path only. A shop name may still contain it.
FAST_CUE = re.compile(
    r"\b(?:actually|sorry|wrong|meant|change|typo|earlier|instead|update|not)\b",
    re.I,
)
EDIT_CUE = re.compile(
    r"\b(?:actually|sorry|wrong|meant|change|typo|earlier|instead|update)\b",
    re.I,
)
QUESTION_WORD = re.compile(r"\b(?:why|what|how|when|where|who|which)\b", re.I)
SMALL_TALK = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "hmm"}
FIELD_SYNONYM = (
    ("shop_name", re.compile(r"\b(?:shop name|legal name|company name|business name|the name|company|firm)\b", re.I)),
    ("city", re.compile(r"\bcity\b", re.I)),
    ("business_type", re.compile(r"\b(?:business type|kind of shop|type of shop)\b", re.I)),
    ("monthly_volume", re.compile(r"\b(?:volume|lakh|crore)\b", re.I)),
    ("payment_methods", re.compile(r"\b(?:payment|upi|cards?|cash|wallet)\b", re.I)),
    ("stores_payer_phones", re.compile(r"\bphones?\b", re.I)),
)
REVIEW_ID = re.compile(r"MR-\d+")
DOC_ID = re.compile(r"\bONB-[A-Z0-9]+(?:-[A-Z0-9]+)*")
SECTION = re.compile(r"\b(ONB-[A-Z0-9]+(?:-[A-Z0-9]+)*)\s*§\s*(\d+(?:\.\d+)?)")
THINK = re.compile(r"<think>.*?</think>", re.S)
LIVE_CLAIM = re.compile(
    r"\b(?:is|are|now|be|been|get|gets|getting)\s+(?:live|active|activated|approved)\b"
    r"|\bturned\s+on\b|\byou(?:'re|\s+are)\s+live\b",
    re.I,
)
HELD = re.compile(r"^## Held\s*\n+(.+?)\s*$", re.M)
MEMO_VOICE = re.compile(r"\bCopilot\b|Document ID", re.I)

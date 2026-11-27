"""The verdict in the service's own words."""

from __future__ import annotations

from copilot.words import ASSIGNEE_WORDS, SLOT_WORDS


def verdict_reply(verdict: dict, answers: dict) -> str:
    shop = str(answers.get("shop_name") or "")
    subject = shop or "The shop"
    outcome = str(verdict.get("outcome") or "")
    parts = _refused(subject) if outcome == "REFUSED" else _open(verdict, shop, subject)
    if verdict.get("injection_flagged"):
        parts.append("Instructions written in the application were not followed. ONB-POL-003 §3.")
    parts.append("The shop is not live.")
    citations = [str(item) for item in verdict.get("citations") or []]
    if citations:
        parts.append("Policy: " + ", ".join(citations) + ".")
    return " ".join(parts)


def _refused(subject: str) -> list[str]:
    return [
        f"No review was opened. {subject} is refused.",
        "This business type is not permitted. ONB-POL-001 §3.",
        "No review id is issued.",
    ]


_REASONS = {
    "NAME_MISMATCH": "not in the shop's legal name",
    "not_legal_name": "not in the shop's legal name",
    "PHOTO_TOO_OLD": "older than 90 days",
    "too_old": "older than 90 days",
    "WRONG_DOCUMENT": "the file is not the requested document",
    "wrong_document": "the file is not the requested document",
    "UNSIGNED": "the addendum is not signed",
    "unsigned": "the addendum is not signed",
    "FORMAT_UNSUPPORTED": "unsupported format",
    "format": "unsupported format",
    "FILE_UNREADABLE": "file unreadable",
}


def _open(verdict: dict, shop: str, subject: str) -> list[str]:
    review_id = verdict.get("review_id")
    parts = [f"Review {review_id}." if review_id else "A review is open."]
    parts.append(_outcome_line(verdict, shop, subject))
    parts.extend(_type_line(verdict))
    missing = [str(item) for item in verdict.get("missing_items") or []]
    inv_map = {x.get("item"): x.get("reason") for x in verdict.get("invalid_items") or [] if isinstance(x, dict)}
    if missing:
        missing_parts = []
        for item in missing:
            name = SLOT_WORDS.get(item, item.replace("_", " "))
            reason = inv_map.get(item)
            if reason and _REASONS.get(reason):
                missing_parts.append(f"{name} ({_REASONS[reason]})")
            else:
                missing_parts.append(name)
        parts.append(f"Missing: {', '.join(missing_parts)}.")
    assignee = _assignee_line(str(verdict.get("assignee") or ""))
    if assignee:
        parts.append(assignee)
    return parts


def _outcome_line(verdict: dict, shop: str, subject: str) -> str:
    if str(verdict.get("outcome") or "") == "RECOMMEND_GO_LIVE":
        return f"Go-live may be recommended for {shop or 'the shop'}. A recommendation is not activation."
    return f"{subject} stays in review."


def _type_line(verdict: dict) -> list[str]:
    if verdict.get("business_type_allowed") is True:
        return ["The business type is permitted."]
    if verdict.get("business_type_allowed") is False:
        return ["The policy does not cover this business type, so a person decides. ONB-POL-001 §3.3."]
    return []


def _assignee_line(assignee: str) -> str:
    if assignee == "HEAD_OF_PAYMENTS":
        return (
            "The stated volume is above ₹40,00,000, so the review goes to the Head of Payments. ONB-POL-002. "
            "Only the Merchant Risk Lead may activate, and only when the pack is complete and the type is "
            "permitted. ONB-POL-001 §4. Both rules apply."
        )
    if assignee in ASSIGNEE_WORDS:
        return f"The review goes to the {ASSIGNEE_WORDS[assignee]}."
    return ""

"""Quit stays in the program. The model names every other action."""

from copilot import acceptable, apply_decision, choose, plain_reply


def test_quit_stays_in_the_program() -> None:
    assert choose("quit") == {"action": "quit"}
    assert choose("Pune") == {"action": "ask"}


def test_a_shop_name_that_starts_with_why_is_the_answer() -> None:
    pending = {"kind": "field", "name": "shop_name"}
    action = apply_decision("Why Not Cafe", {"action": "answer"}, pending, False, [])
    assert action == {"action": "save", "field": "shop_name", "value": "Why Not Cafe"}


def test_why_searches_and_does_not_save() -> None:
    pending = {"kind": "field", "name": "city"}
    for line in ("Why is this needed?", "But why do you need that?"):
        assert apply_decision(line, {"action": "question"}, pending, False, [])["action"] == "why"


def test_a_new_figure_before_submit_is_a_save() -> None:
    action = apply_decision(
        "change the volume",
        {"action": "replace", "field": "monthly_volume", "value": "₹39,00,000"},
        {"kind": "upload", "name": "bank_proof"},
        False,
        [],
    )
    assert action == {"action": "save", "field": "monthly_volume", "value": "₹39,00,000"}


def test_a_figure_after_the_verdict_is_not_a_save() -> None:
    action = apply_decision(
        "change the volume",
        {"action": "replace", "field": "monthly_volume", "value": "₹39,00,000"},
        None,
        True,
        ["shopfront_photo"],
    )
    assert action["action"] == "again"


def test_skip_closes_the_upload() -> None:
    pending = {"kind": "upload", "name": "owner_id"}
    assert apply_decision("skip it", {"action": "missing"}, pending, False, []) == {
        "action": "missing",
        "slot": "owner_id",
    }
    assert apply_decision("I don't have it", {"action": "missing"}, pending, False, []) == {
        "action": "missing",
        "slot": "owner_id",
    }


def test_a_file_name_fills_the_pending_upload() -> None:
    pending = {"kind": "upload", "name": "shopfront_photo"}
    action = apply_decision("front.png", {"action": "file", "file": "front.png"}, pending, False, [])
    assert action == {"action": "file", "slot": "shopfront_photo", "file": "front.png"}


def test_a_live_sentence_is_dropped() -> None:
    assert acceptable("The shop is live. Review MR-2041.", {"verdict": {"review_id": "MR-2041"}}) is False


def test_an_invented_review_number_is_dropped() -> None:
    assert acceptable("Review MR-9999.", {"verdict": {"review_id": "MR-2041"}}) is False


def test_the_stored_review_number_can_be_said() -> None:
    facts = {"verdict": {"review_id": "MR-2041", "outcome": "IN_REVIEW"}}
    assert acceptable("Review MR-2041. The shop stays in review.", facts) is True


def test_the_plain_result_uses_the_stored_words() -> None:
    text = plain_reply(
        {
            "verdict": {
                "outcome": "RECOMMEND_GO_LIVE",
                "review_id": "MR-2041",
                "assignee": "MERCHANT_RISK_LEAD",
                "missing_items": [],
                "citations": ["ONB-POL-001 §4"],
            }
        }
    )
    assert "Go-live may be recommended." in text
    assert "MR-2041" in text
    assert "Merchant Risk Lead" in text
    assert "is live" not in text.lower()

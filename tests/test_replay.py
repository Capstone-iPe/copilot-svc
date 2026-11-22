"""The replay reads the eval table. It does not call the chat model."""

import asyncio
import sys
from pathlib import Path

REPLAY = Path(__file__).resolve().parents[1] / "replay"
sys.path.insert(0, str(REPLAY))

from memory_onb import MemoryOnb
from run import expected, merchant_lines


def test_the_readme_lists_71_shops() -> None:
    rows = expected()
    assert len(rows) == 71
    assert rows["G-001"] == {"outcome": "IN_REVIEW", "holdout": False}
    assert rows["G-047"]["outcome"] == "RECOMMEND_GO_LIVE"
    assert rows["G-002"]["outcome"] == "RECOMMEND_GO_LIVE"
    assert rows["G-014"]["outcome"] == "REFUSED"
    assert rows["G-050"]["holdout"] is False
    assert rows["G-051"]["holdout"] is True


def test_a_dated_photo_and_a_blank_signature_stay_in_the_file_name() -> None:
    from datetime import date, timedelta

    from onb.verifier.rules_document_verifier import RulesDocumentVerifier
    from run import as_said

    photo = {"kind": "upload", "name": "shopfront_photo"}
    old = as_said("[uploads a shopfront photo taken 91 days before submit]", photo)
    fresh = as_said("[uploads a shopfront photo taken 90 days before submit]", photo)
    blank = as_said("[uploads an addendum with a blank signature]", {"kind": "upload", "name": "dpa_addendum"})
    plain = as_said("[uploads a PDF or photo of the business registration]", {"kind": "upload", "name": "business_registration"})
    today = date.today().isoformat()
    checker = RulesDocumentVerifier()
    assert plain == "business_registration.pdf"
    assert (date.today() - timedelta(days=91)).isoformat() in old
    assert (date.today() - timedelta(days=90)).isoformat() in fresh
    assert checker.verify("shopfront_photo", "Old Front", old.encode(), today)["reason_code"] in {"PHOTO_TOO_OLD", "too_old"}
    assert checker.verify("shopfront_photo", "Day Ninety", fresh.encode(), today)["accepted"] is True
    assert "unsigned" in blank
    assert checker.verify("dpa_addendum", "Blank Sign", blank.encode(), today)["reason_code"] in {"UNSIGNED", "unsigned"}


def test_g001_starts_with_the_shop_name() -> None:
    from run import EVAL

    text = (EVAL / "cases" / "G-001.md").read_text(encoding="utf-8")
    assert merchant_lines(text)[1] == "Lotus Tea House"


def test_memory_onb_asks_for_the_shop_name() -> None:
    step = asyncio.run(MemoryOnb().next_step())
    assert step["pending"] == {"kind": "field", "name": "shop_name"}

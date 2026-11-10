"""Digits the merchant typed are not printed back. A review id is."""

from copilot.say.redact import redact


def test_typed_digits_are_hidden() -> None:
    line = "My account is 5521 0038 7716, please confirm it back"
    shown = redact("Your account 5521 0038 7716 is noted. Review MR-2041.", line)
    assert "5521" not in shown
    assert "MR-2041" in shown
    assert "[number hidden]" in shown

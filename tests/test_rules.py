"""Each safety rule names a test. This fails when a rule has none."""

import test_redact
import test_session
import test_turn

RULES = {
    1: "test_an_answer_uses_the_pending_field",
    2: "test_a_shop_name_is_saved_as_typed",
    3: "test_activate_is_refused_before_the_model",
    4: "test_a_figure_after_the_verdict_is_refused",
    5: "test_the_verdict_uses_the_stored_words",
    6: "test_a_live_sentence_is_dropped",
    7: "test_typed_digits_are_hidden",
    8: "test_a_why_does_not_call_onb",
}


def test_every_rule_has_a_test() -> None:
    for name in RULES.values():
        assert hasattr(test_turn, name) or hasattr(test_session, name) or hasattr(test_redact, name), name

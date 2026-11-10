"""The copilot package."""

from copilot.action.decide import apply_decision
from copilot.explain.checker import critic, without_prompt
from copilot.explain.fallback import passage_fallback
from copilot.explain.passages import passages_for_why, prefer_held
from copilot.explain.why import why_instruction, why_question
from copilot.intent.commands import fast_intent
from copilot.intent.guard import guard_intent
from copilot.say.verdict import verdict_reply

__all__ = [
    "apply_decision",
    "critic",
    "fast_intent",
    "guard_intent",
    "passage_fallback",
    "passages_for_why",
    "prefer_held",
    "verdict_reply",
    "why_instruction",
    "why_question",
    "without_prompt",
]

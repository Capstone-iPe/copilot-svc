"""One merchant line in, one Reply out. No print and no input."""

from __future__ import annotations

import json
import logging
import re

from copilot.action.check import check_acts
from copilot.action.decide import apply_decision
from copilot.action.slots import slot_states
from copilot.chat.chat_model import ChatModel
from copilot.corpus.passages import Passages
from copilot.dialogue import DialogueState
from copilot.explain.why import verdict_explanation, why_reply
from copilot.intent.acts import read_acts
from copilot.intent.classifier import stage
from copilot.onb.onb_tools import OnbTools
from copilot.reply import Reply
from copilot.say.files import result_reply
from copilot.say.questions import answers, prompt_for
from copilot.say.refusals import refusal, which_reply
from copilot.words import DIGITS

log = logging.getLogger("copilot")

class Session:
    def __init__(
        self,
        chat: ChatModel,
        onb: OnbTools,
        corpus: Passages,
        application_id: str,
        step: dict,
    ) -> None:
        self.chat = chat
        self.onb = onb
        self.corpus = corpus
        self.application_id = application_id
        self.step = step
        self.dialogue = DialogueState()

    async def turn(self, line: str) -> Reply:
        pending, snapshot, verdict, held = _view(self.step)
        acts, source = read_acts(line, pending, held, snapshot, self.chat.complete, self.dialogue)
        self.dialogue.note("merchant", line)
        if _uses_acts(acts, source):
            reply = await self._acts(line, acts, source, pending, snapshot, verdict)
            self.dialogue.note("assistant", reply.text)
            return reply
        intent = str(acts[0].get("type") or "") if acts else ""
        action = apply_decision(line, intent, pending, held, slot_states(snapshot))
        trace = {"stage": stage(pending, held), "intent": intent, "source": source, "action": action["action"]}
        reply, written, step = await self._answer(line, pending, snapshot, verdict, action, trace)
        trace["reply"] = written
        log.debug("trace %s", json.dumps(trace))
        self.step = step
        if action.get("action") == "save":
            self.dialogue.last_saved = str(action.get("field") or "") or None
            self.dialogue.focus = self.dialogue.last_saved
        self.dialogue.note("assistant", reply)
        return Reply(text=reply, prompt=prompt_for(step), trace=trace, step=step)

    async def _acts(self, line, acts, source, pending, snapshot, verdict) -> Reply:
        held = verdict is not None
        checked = _ordered(check_acts(acts, line, held=held), pending, snapshot)
        texts: list[str] = []
        saved = False
        for act in checked:
            kind = str(act.get("type") or "")
            if kind in _ACT_SAVE:
                wrote = await self._save_act(act, kind == "correct")
                if wrote is None:
                    continue
                texts.append(wrote)
                saved = True
                pending, snapshot, verdict, held = _view(self.step)
                continue
            if kind == "why" or kind == "ask":
                mode = "free" if kind == "ask" else "plain"
                named = act.get("field")
                why_pending = {"kind": "field", "name": named} if named else pending
                reply, _written = why_reply(line, why_pending, self.corpus, self.chat.complete, mode=mode)
                if reply:
                    texts.append(reply)
                continue
            if kind == "refuse":
                texts.append(refusal(str(act.get("reason") or "again"), verdict, line))
                break
            if kind in _ASIDE:
                texts.append(self._aside(kind, line, snapshot))
                continue
        action = "save" if saved else str((checked or acts or [{"type": "again"}])[0].get("type") or "again")
        trace = {
            "stage": stage(pending, held),
            "intent": action,
            "source": source,
            "action": "save" if saved else action,
            "reply": "template",
        }
        log.debug("trace %s", json.dumps(trace))
        return Reply(text=" ".join(part for part in texts if part).strip(), prompt=prompt_for(self.step), trace=trace, step=self.step)

    async def _save_act(self, act: dict, correct: bool) -> str | None:
        field = str(act.get("field") or "")
        value = str(act.get("value_span") or "").strip()
        pending, snapshot, _verdict, _held = _view(self.step)
        stored = answers(snapshot)
        is_pending = (
            isinstance(pending, dict) and pending.get("kind") == "field" and pending.get("name") == field
        )
        already = field in stored and stored.get(field) is not None
        if not field or not value or not (is_pending or already):
            return None
        result = await self.onb.save_answer(self.application_id, field, value)
        if result.get("error"):
            self.step = await self.onb.next_step(self.application_id)
            return refusal("change_how", None, value)
        action = {"action": "save", "field": field, "value": value, "correct": correct}
        reply, _new = result_reply(action, [result], stored)
        self.dialogue.last_saved = field
        self.dialogue.focus = field
        if self.dialogue.awaiting == f"value_for:{field}":
            self.dialogue.awaiting = None
        self.step = await self.onb.next_step(self.application_id)
        return reply

    def _aside(self, kind: str, line: str, snapshot: dict) -> str:
        if kind == "chitchat":
            return "I'm here. We can keep going whenever you're ready."
        if kind == "pause":
            return "No rush. I'll hold this question."
        if kind == "undo":
            return "I can't undo a saved answer. Tell me the field and the new value, and I'll update it."
        if kind == "recap":
            stored = answers(snapshot)
            if not stored:
                return "Nothing is saved yet."
            parts = [
                f"{name.replace('_', ' ')} is {DIGITS.sub('[number hidden]', str(value))}"
                for name, value in stored.items()
                if value
            ]
            return "So far, " + "; ".join(parts) + "."
        field = _named_field(line)
        if field:
            self.dialogue.awaiting = f"value_for:{field}"
            return "Sure. What should it be?"
        return "Tell me which answer to change and what it should be."

    async def _answer(self, line, pending, snapshot, verdict, action, trace):
        kind = action["action"]
        if kind == "why":
            reply, written = why_reply(
                line, pending, self.corpus, self.chat.complete, mode=str(action.get("mode") or "plain")
            )
            return reply, written, self.step
        if kind == "refuse":
            trace["reason"] = action["reason"]
            return refusal(action["reason"], verdict, line), "template", self.step
        if kind == "which":
            return which_reply(action["slots"]), "template", self.step
        if kind == "again":
            return "", "template", self.step
        return await self._act(snapshot, action, trace)

    async def _act(self, snapshot, action, trace):
        results = await self._tools(action)
        answers = snapshot.get("answers") if isinstance(snapshot.get("answers"), dict) else {}
        reply, new_verdict = result_reply(action, results, answers)
        written = "template"
        if new_verdict and action["action"] in {"submit", "file"}:
            extra = verdict_explanation(new_verdict, self.corpus, self.chat.complete)
            if extra:
                reply += " " + extra
                written = "template+model"
        trace["outcome"] = (new_verdict or {}).get("outcome")
        step = await self.onb.next_step(self.application_id)
        return reply, written, step

    async def _tools(self, action: dict) -> list[dict]:
        kind = action["action"]
        aid = self.application_id
        if kind == "save":
            return [await self.onb.save_answer(aid, action["field"], action["value"])]
        if kind == "file":
            return [await self.onb.save_file(aid, action["slot"], file=action["file"])]
        if kind == "missing":
            return await self._missing(action["slots"])
        if kind == "submit":
            return [await self.onb.submit(aid)]
        return [await self.onb.get_review(aid)]

    async def _missing(self, slots: list[str]) -> list[dict]:
        results = []
        for slot in slots:
            results.append(await self.onb.save_file(self.application_id, slot, missing=True))
            if results[-1].get("error"):
                break
        return results

_ASIDE = {"chitchat", "pause", "recap", "undo", "change_request"}
_ACT_SAVE = {"answer", "correct"}


_NAMED = {
    "shop name": "shop_name",
    "legal name": "shop_name",
    "city": "city",
    "business type": "business_type",
    "volume": "monthly_volume",
    "payment": "payment_methods",
    "phone": "stores_payer_phones",
    "phones": "stores_payer_phones",
}


def _named_field(line: str) -> str | None:
    match = re.search(
        r"\b(shop name|legal name|city|business type|volume|payment|phones?)\b",
        line,
        re.I,
    )
    if not match:
        return None
    return _NAMED.get(match.group(1).lower())


def _uses_acts(acts: list[dict], source: str) -> bool:
    if source in {"code", "awaiting", "model"}:
        return True
    if len(acts) != 1:
        return True
    return str(acts[0].get("type") or "") in _ASIDE


def _ordered(acts: list[dict], pending, snapshot) -> list[dict]:
    name = pending.get("name") if isinstance(pending, dict) and pending.get("kind") == "field" else None
    stored = answers(snapshot)

    def key(item: tuple[int, dict]) -> tuple[int, int]:
        index, act = item
        field = act.get("field")
        kind = act.get("type")
        if kind in _ACT_SAVE and field in stored and stored.get(field) is not None and field != name:
            rank = 0
        elif kind in _ACT_SAVE and field == name:
            rank = 1
        elif kind in _ACT_SAVE:
            rank = 3
        else:
            rank = 2
        return rank, index

    return [act for _, act in sorted(enumerate(acts), key=key)]


def _view(step: dict):
    pending = step.get("pending") if isinstance(step.get("pending"), dict) else None
    snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
    verdict = snapshot.get("verdict") if isinstance(snapshot.get("verdict"), dict) else None
    return pending, snapshot, verdict, verdict is not None

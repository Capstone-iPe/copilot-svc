"""One merchant line in, one Reply out. No print and no input."""

from __future__ import annotations

import json
import logging
import re

from copilot.action.check import check_acts
from copilot.action.closed import heard, list_value
from copilot.action.decide import apply_decision
from copilot.action.slots import slot_states
from copilot.chat.chat_model import ChatModel
from copilot.corpus.passages import Passages
from copilot.dialogue import DialogueState
from copilot.explain.why import verdict_explanation, why_reply
from copilot.intent.acts import read_acts
from copilot.intent.classifier import stage
from copilot.observability import note_fallback
from copilot.onb.onb_tools import OnbTools
from copilot.reply import Reply
from copilot.say.files import result_reply
from copilot.say.questions import answers, prompt_for
from copilot.say.refusals import refusal, which_reply
from copilot.words import DIGITS, FIELD_OF, FIELD_WORD

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

    async def turn(self, line: str, payload: str | None = None) -> Reply:
        pending, snapshot, verdict, held = _view(self.step)
        if pending and pending.get("name"):
            self.dialogue.focus = str(pending["name"])
        acts, source = read_acts(line, pending, held, snapshot, self.chat.complete, self.dialogue)
        log.info("taking decision: source=%s acts=%s", source, _brief(acts))
        self.dialogue.note("merchant", line)
        if source not in {"guard", "command"} or any(str(a.get("type")) == "change_doc" for a in acts):
            reply = await self._acts(line, acts, source, pending, snapshot, verdict, payload=payload)
            self.dialogue.note("assistant", reply.text)
            return reply
        intent = str(acts[0].get("type") or "") if acts else ""
        action = apply_decision(line, intent, pending, held, slot_states(snapshot))
        if (
            intent == "upload"
            and action.get("action") == "which"
            and self.dialogue.awaiting
            and self.dialogue.awaiting.startswith("upload_for:")
        ):
            from copilot.action.change import file_in

            action = {
                "action": "file",
                "slot": self.dialogue.awaiting.split(":", 1)[1],
                "file": file_in(line) or line,
            }
        if payload and action.get("action") == "file":
            action["file"] = payload
        trace = {"stage": stage(pending, held), "intent": intent, "source": source, "action": action["action"]}
        reply, written, step = await self._answer(line, pending, snapshot, verdict, action, trace)
        trace["reply"] = written
        log.debug("trace %s", json.dumps(trace))
        self.step = step
        if action.get("action") == "save":
            self.dialogue.last_saved = str(action.get("field") or "") or None
            self.dialogue.focus = self.dialogue.last_saved
            self.dialogue.remember(self.dialogue.last_saved or "", str(action.get("value") or ""))
        if action.get("action") in {"file", "save", "missing", "submit", "review"}:
            self.dialogue.awaiting = None
        self.dialogue.note("assistant", reply)
        return Reply(text=reply, prompt=prompt_for(step), trace=trace, step=step)

    async def _acts(self, line, acts, source, pending, snapshot, verdict, payload: str | None = None) -> Reply:
        held = verdict is not None
        checked = _ordered(
            check_acts(
                acts,
                line,
                held=held,
                pending=pending,
                earlier=self.dialogue.values,
                last_saved=self.dialogue.last_saved,
                awaiting=self.dialogue.awaiting,
            ),
            pending,
            snapshot,
        )
        log.info("after check: %s", _brief(checked))
        texts: list[str] = []
        saved = False
        prior_wait = self.dialogue.awaiting
        for act in checked:
            kind = str(act.get("type") or "")
            if kind in _ACT_SAVE:
                wrote, did_save = await self._save_act(act, kind == "correct")
                if wrote:
                    texts.append(wrote)
                if did_save:
                    saved = True
                    pending, snapshot, verdict, held = _view(self.step)
                continue
            if kind == "why" or kind == "ask":
                mode = "free" if kind == "ask" else "plain"
                named = None if kind == "ask" else act.get("field")
                why_pending = {"kind": "field", "name": named} if named else pending
                reply, _written = why_reply(line, why_pending, self.corpus, self.chat.complete, mode=mode)
                if reply:
                    texts.append(reply)
                continue
            if kind == "refuse":
                note_fallback("refusal")
                texts.append(refusal(str(act.get("reason") or "again"), verdict, line))
                break
            if kind == "recall_miss":
                label = str(act.get("field") or "answer").replace("_", " ")
                texts.append(f"I only have the current {label}, so there isn't an earlier one to put back.")
                continue
            if kind == "confirm":
                field = str(act.get("field") or "")
                value = str(act.get("value_span") or "")
                self.dialogue.awaiting = f"confirm:{field}"
                self.dialogue.proposed = {"field": field, "value": value}
                texts.append(f"Did you mean {value} for the {field.replace('_', ' ')}?")
                continue
            if kind == "confirm_yes" and self.dialogue.proposed:
                wrote, did_save = await self._save_act(
                    {"field": self.dialogue.proposed["field"], "value_span": self.dialogue.proposed["value"]},
                    True,
                )
                self.dialogue.proposed = None
                self.dialogue.awaiting = None
                if wrote:
                    texts.append(wrote)
                if did_save:
                    saved = True
                continue
            if kind == "confirm_no":
                self.dialogue.proposed = None
                self.dialogue.awaiting = None
                texts.append("Okay, we'll leave that as it is.")
                continue
            if kind in {"upload", "missing", "submit", "review_id"}:
                action = apply_decision(line, kind, pending, held, slot_states(snapshot))
                if kind == "upload" and action.get("action") == "which" and self.dialogue.awaiting and self.dialogue.awaiting.startswith("upload_for:"):
                    target_slot = self.dialogue.awaiting.split(":", 1)[1]
                    from copilot.action.change import file_in
                    action = {"action": "file", "slot": target_slot, "file": file_in(line) or line}
                if payload and action.get("action") == "file":
                    action["file"] = payload
                reply, _written, step = await self._answer(line, pending, snapshot, verdict, action, {})
                self.step = step
                if reply:
                    texts.append(reply)
                if action.get("action") in {"save", "file", "missing", "submit", "review"}:
                    self.dialogue.awaiting = None
                    saved = True
                    pending, snapshot, verdict, held = _view(self.step)
                continue
            if kind in _ASIDE:
                texts.append(self._aside(kind, line, snapshot, act))
                continue
        if self.dialogue.awaiting == prior_wait and prior_wait:
            kinds = {str(act.get("type") or "") for act in checked}
            if not kinds or not kinds <= _KEEP_WAIT:
                self.dialogue.awaiting = None
                self.dialogue.proposed = None
        self._missed(pending, saved, checked)
        if not any(part.strip() for part in texts) and not saved:
            kinds = {str(act.get("type") or "") for act in checked}
            if not kinds or not kinds <= _KEEP_WAIT:
                texts.append("Sorry, I didn't catch that. Could you say it again?")
        action = "save" if saved else str((checked or acts or [{"type": "again"}])[0].get("type") or "again")
        trace = {
            "stage": stage(pending, held),
            "intent": action,
            "source": source,
            "action": "save" if saved else action,
            "reply": "template",
        }
        for act in checked:
            if str(act.get("type")) == "change_doc":
                trace["asking"] = act.get("slot")
        log.debug("trace %s", json.dumps(trace))
        return Reply(
            text=" ".join(part for part in texts if part).strip(),
            prompt=_prompt(self),
            trace=trace,
            step=self.step,
        )

    async def _save_act(self, act: dict, correct: bool) -> tuple[str | None, bool]:
        field = str(act.get("field") or "")
        value = str(act.get("value_span") or "").strip()
        said = str(act.get("said") or value)
        picked = list_value(field, value) or list_value(field, said)
        shown = value
        phrase = heard(field, said)
        if picked:
            value = picked
            if phrase and phrase.casefold() != picked.casefold():
                shown = f"{phrase} (listed as {picked})"
        pending, snapshot, _verdict, _held = _view(self.step)
        stored = answers(snapshot)
        is_pending = (
            isinstance(pending, dict) and pending.get("kind") == "field" and pending.get("name") == field
        )
        already = field in stored and stored.get(field) is not None
        if not field or not value:
            return None, False
        if not (is_pending or already):
            label = field.replace("_", " ")
            return f"I still need the current answer before I can store the {label}.", False
        result = await self.onb.save_answer(self.application_id, field, value)
        action = {"action": "save", "field": field, "value": value, "shown": shown, "correct": correct}
        if result.get("error"):
            note_fallback("onb_rejected_answer")
            reply, _new = result_reply(action, [result], stored)
            self.step = await self.onb.next_step(self.application_id)
            return reply, False
        reply, _new = result_reply(action, [result], stored)
        self.dialogue.last_saved = field
        self.dialogue.focus = field
        self.dialogue.remember(field, value)
        if self.dialogue.awaiting == f"value_for:{field}":
            self.dialogue.awaiting = None
        self.step = await self.onb.next_step(self.application_id)
        return reply, True

    def _missed(self, pending, saved: bool, checked: list[dict]) -> None:
        name = pending.get("name") if isinstance(pending, dict) and pending.get("kind") == "field" else None
        kinds = {str(act.get("type") or "") for act in checked}
        if saved or not name:
            self.dialogue.misses = 0
            self.dialogue.miss_field = None
            return
        if kinds and kinds <= _KEEP_WAIT:
            return
        if self.dialogue.miss_field != name:
            self.dialogue.misses = 1
            self.dialogue.miss_field = name
            return
        self.dialogue.misses += 1

    def _aside(self, kind: str, line: str, snapshot: dict, act: dict | None = None) -> str:
        if kind == "chitchat":
            low = line.strip().lower()
            if "thank" in low:
                return "You're welcome."
            if re.search(r"\b(?:hi|hello|hey)\b", low):
                return "Hi!"
            if re.search(r"\b(?:ok|okay|sure|great|yes|haan)\b", low):
                return "Great."
            return ""
        if kind == "change_doc":
            from copilot.say.questions import WEB_UPLOADS
            from copilot.words import SLOT_WORDS

            slot = str((act or {}).get("slot") or "business_registration")
            self.dialogue.awaiting = f"upload_for:{slot}"
            self.dialogue.focus = slot
            prompt = WEB_UPLOADS.get(slot)
            if prompt:
                return f"Sure. {prompt}"
            words = SLOT_WORDS.get(slot, slot)
            return f"Sure, tap Upload to add the {words}. PDF, JPG, or PNG."
        if kind == "pause":
            return "Sure, take your time. Everything so far is saved. Just come back and we'll continue from here."
        if kind == "undo":
            last = self.dialogue.last_saved
            if last:
                self.dialogue.awaiting = f"value_for:{last}"
                return f"Sure, what should the {last.replace('_', ' ')} be?"
            self.dialogue.awaiting = "which_field"
            return (
                "Which answer would you like to change: shop name, city, business type, "
                "monthly volume, payment methods, or payer phones?"
            )
        if kind == "recap":
            return _recap(snapshot)
        if isinstance(snapshot.get("verdict"), dict):
            return "Stored answers stay as stored. " + _recap(snapshot)
        field = str((act or {}).get("field") or "") or (_named_field(line) or "")
        if field:
            self.dialogue.awaiting = f"value_for:{field}"
            return f"Sure, what should the {field.replace('_', ' ')} be?"
        self.dialogue.awaiting = "which_field"
        return (
            "Which answer would you like to change: shop name, city, business type, "
            "monthly volume, payment methods, or payer phones?"
        )

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
        if any(result.get("error") for result in results):
            note_fallback("onb_rejected_action")
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

_ASIDE = {"chitchat", "pause", "recap", "undo", "change_request", "change_doc"}
_KEEP_WAIT = {"why", "ask", "chitchat", "recap", "pause"}
_ACT_SAVE = {"answer", "correct"}


def _recap(snapshot: dict) -> str:
    stored = answers(snapshot)
    if not stored:
        return "Nothing is saved yet."
    parts = []
    for name, value in stored.items():
        if not value:
            continue
        shown = str(value)
        if name != "monthly_volume":
            shown = DIGITS.sub("[number hidden]", shown)
        parts.append(f"{name.replace('_', ' ')} is {shown}")
    return "So far, " + "; ".join(parts) + "."


def _prompt(session: Session) -> str:
    pending = session.step.get("pending") if isinstance(session.step.get("pending"), dict) else None
    if (
        pending
        and pending.get("name") == "stores_payer_phones"
        and session.dialogue.miss_field == "stores_payer_phones"
        and session.dialogue.misses >= 2
    ):
        return "Just type yes or no."
    waiting = session.dialogue.awaiting or ""
    if waiting.startswith("value_for:"):
        from copilot.say.questions import QUESTIONS

        field = waiting.split(":", 1)[1]
        question = QUESTIONS.get(field)
        if question:
            return question
    if waiting.startswith("upload_for:"):
        from copilot.say.questions import WEB_UPLOADS

        slot = waiting.split(":", 1)[1]
        prompt = WEB_UPLOADS.get(slot)
        if prompt:
            return prompt
    return prompt_for(session.step)


def _brief(acts: list[dict]) -> str:
    short = [{"type": act.get("type"), "field": act.get("field"), "value_span": act.get("value_span")} for act in acts]
    return json.dumps(short, ensure_ascii=False)


def _named_field(line: str) -> str | None:
    match = FIELD_WORD.search(line)
    if not match:
        return None
    return FIELD_OF.get(match.group(1).lower())


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

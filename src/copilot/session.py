"""One merchant line in, one Reply out. No print and no input."""

from __future__ import annotations

import json
import logging

from copilot.action.decide import apply_decision
from copilot.action.slots import slot_states
from copilot.chat.chat_model import ChatModel
from copilot.corpus.passages import Passages
from copilot.explain.why import verdict_explanation, why_reply
from copilot.intent.classifier import stage
from copilot.intent.reader import read_intent
from copilot.onb.onb_tools import OnbTools
from copilot.reply import Reply
from copilot.say.files import result_reply
from copilot.say.questions import prompt_for
from copilot.say.refusals import refusal, which_reply

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

    async def turn(self, line: str) -> Reply:
        pending, snapshot, verdict, held = _view(self.step)
        intent, source = read_intent(line, pending, held, self.chat.complete)
        action = apply_decision(line, intent, pending, held, slot_states(snapshot))
        trace = {"stage": stage(pending, held), "intent": intent, "source": source, "action": action["action"]}
        reply, written, step = await self._answer(line, pending, snapshot, verdict, action, trace)
        trace["reply"] = written
        log.info("trace %s", json.dumps(trace))
        self.step = step
        return Reply(text=reply, prompt=prompt_for(step), trace=trace, step=step)

    async def _answer(self, line, pending, snapshot, verdict, action, trace):
        kind = action["action"]
        if kind == "why":
            reply, written = why_reply(line, pending, self.corpus, self.chat.complete)
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

def _view(step: dict):
    pending = step.get("pending") if isinstance(step.get("pending"), dict) else None
    snapshot = step.get("snapshot") if isinstance(step.get("snapshot"), dict) else {}
    verdict = snapshot.get("verdict") if isinstance(snapshot.get("verdict"), dict) else None
    return pending, snapshot, verdict, verdict is not None

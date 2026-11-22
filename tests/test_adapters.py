"""Every consumer goes through an adapter."""

from copilot.adapters.cli import CliAdapter
from copilot.adapters.replay import ReplayAdapter
from copilot.adapters.web import WebAdapter
from copilot.reply import Reply

STEP = {
    "application_id": "app_1",
    "pending": {"kind": "field", "name": "city"},
    "snapshot": {"answers": {"shop_name": "Lotus Tea House"}, "files": {}},
}

VERDICT_STEP = {
    "application_id": "app_1",
    "pending": None,
    "snapshot": {
        "answers": {"shop_name": "Lotus Tea House"},
        "files": {},
        "verdict": {
            "outcome": "IN_REVIEW",
            "review_id": "MR-2041",
            "assignee": "MERCHANT_RISK_LEAD",
            "missing_items": ["bank_proof"],
            "citations": ["ONB-POL-001 §2"],
        },
    },
}


def _reply(text="Saved.", prompt="Which city is the shop in?", step=STEP, action="save") -> Reply:
    return Reply(text=text, prompt=prompt, trace={"action": action}, step=step)


def test_cli_adapter_prints_text_and_prompt() -> None:
    adapter = CliAdapter()
    opened = adapter.open(STEP)
    assert opened["text"] == ""
    assert "city" in opened["prompt"].lower()
    assert opened["messages"] == [opened["prompt"]]
    out = adapter.render(_reply(text="My account is 1234 5678", prompt="Next."), line="My account is 1234 5678")
    assert "[number hidden]" in out["text"]
    assert out["prompt"] == "Next."
    assert len(out["messages"]) == 2
    assert out["messages"][1] == "Next."


def test_reply_builds_two_messages() -> None:
    reply = _reply(text="Saved.", prompt="Will the shop store payer phone numbers? Yes or no.")
    assert reply.messages == [
        "Saved.",
        "Will the shop store payer phone numbers? Yes or no.",
    ]


def test_replay_adapter_exposes_the_checker_fields() -> None:
    adapter = ReplayAdapter()
    out = adapter.render(_reply(step=VERDICT_STEP, action="submit"), line="Submit")
    assert out["outcome"] == "IN_REVIEW"
    assert out["review_id"] == "MR-2041"
    assert out["action"] == "submit"
    assert out["pending_name"] is None


def test_web_adapter_carries_asking_and_a_result_card() -> None:
    adapter = WebAdapter()
    opened = adapter.open(STEP)
    assert opened["asking"] == "city"
    assert opened["prompt"]["field"] == "city"
    assert opened["prompt"]["pills"] == []
    assert len(opened["messages"]) == 2
    assert opened["messages"][0]["text"].startswith("Welcome to iPe.")
    assert "city" in opened["messages"][1]["text"].lower()
    named = adapter.open(STEP, merchant_name="Rupesh")
    assert named["messages"][0]["text"].startswith("Hi Rupesh, welcome to iPe.")
    assert named["messages"][1]["text"] == opened["messages"][1]["text"]
    out = adapter.render(_reply(text="A review is open.", prompt="", step=VERDICT_STEP), line="Submit")
    assert out["asking"] is None
    assert out["assistant_texts"] == ["A review is open."]
    assert out["card"]["type"] == "result"
    assert out["card"]["review_id"] == "MR-2041"
    assert out["card"]["outcome"] == "IN_REVIEW"
    assert out["result"]["assignee"] == "MERCHANT_RISK_LEAD"


def test_web_adapter_smart_suggestion_pills() -> None:
    from copilot.adapters.web import prompt_view
    b_pills = prompt_view("business_type")["pills"]
    labels = [p["label"] for p in b_pills]
    assert "Restaurant" in labels
    assert "Grocery" in labels
    assert "Retail" in labels
    assert "Why is this needed?" in labels

    p_pills = prompt_view("payment_methods")["pills"]
    p_labels = [p["label"] for p in p_pills]
    assert "UPI" in p_labels
    assert "Cards" in p_labels
    assert "UPI and cards" in p_labels

    ph_pills = prompt_view("stores_payer_phones")["pills"]
    ph_labels = [p["label"] for p in ph_pills]
    assert "Yes" in ph_labels
    assert "No" in ph_labels

    u_pills = prompt_view("business_registration")["pills"]
    u_labels = [p["label"] for p in u_pills]
    assert "Upload business registration" in u_labels
    assert "I don't have this" in u_labels
    assert "Why is this needed?" in u_labels

    s_pills = prompt_view("submit")["pills"]
    s_labels = [p["label"] for p in s_pills]
    assert "Submit" in s_labels
    assert "Change an answer" in s_labels



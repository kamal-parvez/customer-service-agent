"""Tests for agent.py's orchestration and error-fallback behavior.

The LLM call is monkeypatched throughout so the suite runs offline.
"""

from customer_service_agent import agent as agent_module
from customer_service_agent.agent import customer_service_agent
from customer_service_agent.llm import LLMConfigError


FAKE_PLAN = """
<execute_python>
# 1) Look up Aviator sunglasses
item = Query()
rows = inventory_tbl.search(item.name == "Aviator")
answer_text = f"Yes, we have {rows[0]['quantity_in_stock']} Aviators in stock."
STATUS = "success"
</execute_python>
"""


def test_customer_service_agent_end_to_end(store, monkeypatch):
    _, inventory_tbl, transactions_tbl = store

    monkeypatch.setattr(
        agent_module, "generate_llm_code", lambda *args, **kwargs: FAKE_PLAN
    )

    result = customer_service_agent(
        "Do you have Aviators?",
        inventory_tbl=inventory_tbl,
        transactions_tbl=transactions_tbl,
    )

    assert result["status"] == "success"
    assert "Aviators in stock" in result["answer"]
    assert result["error"] is None


def test_customer_service_agent_reseed_resets_data(store, monkeypatch):
    _, inventory_tbl, transactions_tbl = store
    inventory_tbl.update({"quantity_in_stock": 0})

    monkeypatch.setattr(
        agent_module, "generate_llm_code", lambda *args, **kwargs: FAKE_PLAN
    )

    customer_service_agent(
        "Do you have Aviators?",
        inventory_tbl=inventory_tbl,
        transactions_tbl=transactions_tbl,
        reseed=True,
    )

    assert all(row["quantity_in_stock"] > 0 for row in inventory_tbl.all())


def test_customer_service_agent_falls_back_when_llm_call_fails(store, monkeypatch):
    """An LLM API error must produce a fallback answer, not crash the caller."""
    _, inventory_tbl, transactions_tbl = store

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(agent_module, "generate_llm_code", _boom)

    result = customer_service_agent(
        "Do you have Aviators?",
        inventory_tbl=inventory_tbl,
        transactions_tbl=transactions_tbl,
    )

    assert result["status"] == "llm_error"
    assert result["answer"]  # non-empty, user-facing fallback


def test_customer_service_agent_reraises_llm_config_error(store, monkeypatch):
    """LLMConfigError should propagate, not get swallowed into the generic fallback."""
    _, inventory_tbl, transactions_tbl = store

    def _boom(*args, **kwargs):
        raise LLMConfigError("GOOGLE_API_KEY is not set.")

    monkeypatch.setattr(agent_module, "generate_llm_code", _boom)

    try:
        customer_service_agent(
            "Do you have Aviators?",
            inventory_tbl=inventory_tbl,
            transactions_tbl=transactions_tbl,
        )
        assert False, "expected LLMConfigError to propagate"
    except LLMConfigError:
        pass


def test_customer_service_agent_falls_back_when_answer_text_missing(store, monkeypatch):
    """A clean run with no answer_text must show a fallback message, not "None"."""
    _, inventory_tbl, transactions_tbl = store
    plan_without_answer = """
<execute_python>
rows = inventory_tbl.search(Query().name == "Aviator")
STATUS = "success"
</execute_python>
"""
    monkeypatch.setattr(
        agent_module,
        "generate_llm_code",
        lambda *args, **kwargs: plan_without_answer,
    )

    result = customer_service_agent(
        "Do you have Aviators?",
        inventory_tbl=inventory_tbl,
        transactions_tbl=transactions_tbl,
    )

    assert result["answer"]
    assert result["answer"] != "None"

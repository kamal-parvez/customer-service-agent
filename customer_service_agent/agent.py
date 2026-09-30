"""End-to-end orchestration: request -> plan-as-code -> safe execution -> answer."""

from __future__ import annotations

import logging
from typing import Any

from tinydb.table import Table

from customer_service_agent.db import create_inventory, create_transactions
from customer_service_agent.executor import execute_generated_code
from customer_service_agent.llm import LLMConfigError, generate_llm_code

logger = logging.getLogger(__name__)

# Fallback answers for: (1) the LLM call itself failing, (2) the generated
# plan crashing, (3) the plan running but never setting answer_text.
_LLM_FAILURE_ANSWER = (
    "Sorry, I'm having trouble reaching the assistant right now. "
    "Please try again in a moment."
)
_MISSING_ANSWER_FALLBACK = (
    "Sorry, I couldn't work out a clear answer for that. "
    "Could you rephrase your request?"
)
_EXECUTION_FAILURE_ANSWER = (
    "Sorry, something went wrong handling that request. "
    "Please try again or rephrase it."
)


def customer_service_agent(
    question: str,
    *,
    inventory_tbl: Table,
    transactions_tbl: Table,
    model: str | None = None,
    temperature: float | None = None,
    reseed: bool = False,
) -> dict[str, Any]:
    """Handle one customer request end to end: generate a plan, execute it,
    and always return a non-empty, user-facing answer.

    LLMConfigError propagates (so callers can show a "set your API key"
    message); every other failure falls back to a generic message instead
    of returning None or a raw traceback.
    """
    if reseed:
        create_inventory(inventory_tbl)
        create_transactions(transactions_tbl)

    logger.info("customer question: %s", question)

    try:
        full_content = generate_llm_code(
            question,
            inventory_tbl=inventory_tbl,
            transactions_tbl=transactions_tbl,
            model=model,
            temperature=temperature,
        )
    except LLMConfigError:
        raise  # not configured at all -- let the caller show a distinct message
    except Exception:
        logger.exception("LLM call failed for question: %r", question)
        return {
            "question": question,
            "full_content": None,
            "code": None,
            "stdout": "",
            "error": "LLM call failed after retries.",
            "status": "llm_error",
            "answer": _LLM_FAILURE_ANSWER,
            "inventory_after": inventory_tbl.all(),
            "transactions_after": transactions_tbl.all(),
        }

    logger.debug("plan-as-code response:\n%s", full_content)

    exec_result = execute_generated_code(
        full_content,
        inventory_tbl=inventory_tbl,
        transactions_tbl=transactions_tbl,
        user_request=question,
    )

    if exec_result["error"]:
        logger.error("execution error:\n%s", exec_result["error"])
    if exec_result["stdout"]:
        logger.info("plan logs: %s", exec_result["stdout"])

    answer = exec_result["answer"]
    if not answer:
        if exec_result["error"]:
            logger.warning("plan failed with no answer_text; question=%r", question)
            answer = _EXECUTION_FAILURE_ANSWER
        else:
            logger.warning(
                "plan executed with no error but set no answer_text; question=%r",
                question,
            )
            answer = _MISSING_ANSWER_FALLBACK

    return {
        "question": question,
        "full_content": full_content,
        "code": exec_result["code"],
        "stdout": exec_result["stdout"],
        "error": exec_result["error"],
        "status": exec_result["status"],
        "answer": answer,
        "inventory_after": exec_result["inventory_after"],
        "transactions_after": exec_result["transactions_after"],
    }

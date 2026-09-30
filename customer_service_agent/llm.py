"""Thin wrapper around the Gemini API: turns a question + table schema into
a raw plan-as-code response. Doesn't execute anything -- see executor.py.
"""

from __future__ import annotations

import time
from functools import lru_cache

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tinydb.table import Table

from customer_service_agent.config import settings
from customer_service_agent.db import build_schema_block
from customer_service_agent.prompts import PLAN_AS_CODE_PROMPT

# Retry on transient 503s. 429 quota errors are NOT retried -- a short
# backoff won't help against a daily quota.
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2.0


class LLMConfigError(RuntimeError):
    """Raised when the Gemini client can't be built (e.g. missing API key)."""


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Return a process-wide, lazily-created Gemini client.

    Raises:
        LLMConfigError: If GOOGLE_API_KEY isn't set.
    """
    if not settings.google_api_key:
        raise LLMConfigError(
            "GOOGLE_API_KEY is not set. Add it to your .env file "
            "(see .env.example)."
        )
    return genai.Client(api_key=settings.google_api_key)


def generate_llm_code(
    user_request: str,
    *,
    inventory_tbl: Table,
    transactions_tbl: Table,
    model: str | None = None,
    temperature: float | None = None,
) -> str:
    """Ask Gemini to produce a plan-with-code response for user_request.

    Returns the model's raw text, typically containing an
    <execute_python>...</execute_python> block.
    """
    schema_block = build_schema_block(inventory_tbl, transactions_tbl)
    prompt = PLAN_AS_CODE_PROMPT.format(
        schema_block=schema_block, question=user_request
    )

    client = get_client()
    config = types.GenerateContentConfig(
        temperature=settings.temperature if temperature is None else temperature,
        system_instruction=(
            "You write safe, well-commented TinyDB code to handle data "
            "questions and updates."
        ),
    )
    resolved_model = model or settings.gemini_model

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=resolved_model, contents=prompt, config=config
            )
            return response.text or ""
        except genai_errors.ServerError as exc:
            last_error = exc
            if attempt < _MAX_RETRIES - 1:  # no point sleeping after the last try
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
    assert last_error is not None  # loop always returns or sets this
    raise last_error

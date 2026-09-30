"""Execute LLM-generated "plan-as-code" in an isolated subprocess."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from tinydb.table import Table

from customer_service_agent.sandbox_common import extract_execute_block

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_TIMEOUT_SECONDS = 10.0


def _subprocess_env() -> dict[str, str]:
    """Minimal environment for the sandbox worker -- excludes API keys and
    everything else in this process's environment.
    """
    keep = ("PATH", "SYSTEMROOT", "PYTHONIOENCODING")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return env


def _timeout_seconds() -> float:
    """Sandbox timeout in seconds (env override, falls back on bad values)."""
    try:
        return float(
            os.getenv("EXECUTOR_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT_SECONDS))
        )
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS


def _error_result(
    code: str,
    error: str,
    status: str,
    inventory_tbl: Table,
    transactions_tbl: Table,
) -> dict[str, Any]:
    """Result dict for a pre-execution failure (timeout/crash/bad output),
    same shape as a normal successful result.
    """
    return {
        "code": code,
        "stdout": "",
        "error": error,
        "answer": None,
        "status": status,
        "inventory_after": inventory_tbl.all(),
        "transactions_after": transactions_tbl.all(),
    }


def execute_generated_code(
    code_or_content: str,
    *,
    inventory_tbl: Table,
    transactions_tbl: Table,
    user_request: Optional[str] = None,
) -> dict[str, Any]:
    """Execute a plan-as-code response in an isolated subprocess.

    Accepts raw code or full model content wrapped in <execute_python>
    tags. Mutates inventory_tbl/transactions_tbl in place, replacing them
    with the subprocess's reported post-execution state.
    """
    code = extract_execute_block(code_or_content)

    payload = json.dumps(
        {
            "code": code,
            "user_request": user_request or "",
            "inventory_rows": inventory_tbl.all(),
            "transaction_rows": transactions_tbl.all(),
        }
    )

    timeout = _timeout_seconds()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "customer_service_agent.sandbox_worker"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        return _error_result(
            code,
            f"Execution timed out after {timeout:.0f}s.",
            "execution_timeout",
            inventory_tbl,
            transactions_tbl,
        )

    if proc.returncode != 0 or not proc.stdout.strip():
        detail = proc.stderr.strip() or f"exit code {proc.returncode}"
        return _error_result(
            code,
            f"Sandbox worker failed: {detail}",
            "sandbox_crash",
            inventory_tbl,
            transactions_tbl,
        )

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _error_result(
            code,
            f"Sandbox worker returned invalid output: {proc.stdout[:500]!r}",
            "sandbox_invalid_output",
            inventory_tbl,
            transactions_tbl,
        )

    # The subprocess only saw a disposable copy of the data; sync the real
    # tables with whatever it reports back.
    inventory_tbl.truncate()
    if result.get("inventory_after"):
        inventory_tbl.insert_multiple(result["inventory_after"])
    transactions_tbl.truncate()
    if result.get("transactions_after"):
        transactions_tbl.insert_multiple(result["transactions_after"])

    return {
        "code": code,
        "stdout": result.get("stdout", ""),
        "error": result.get("error"),
        "answer": result.get("answer"),
        "status": result.get("status"),
        "inventory_after": inventory_tbl.all(),
        "transactions_after": transactions_tbl.all(),
    }

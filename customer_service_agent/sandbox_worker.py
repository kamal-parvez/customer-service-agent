"""Subprocess entry point that executes untrusted, LLM-generated code.
"""

from __future__ import annotations

import io
import json
import sys
import traceback

from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from customer_service_agent.sandbox_common import build_sandbox_namespace


def _apply_resource_limits() -> None:
    """Best-effort CPU/memory caps, on top of the caller's wall-clock
    timeout. Not available on all platforms; failures here are ignored.
    """
    try:
        import resource

        cpu_seconds = 10
        address_space_bytes = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(
            resource.RLIMIT_AS, (address_space_bytes, address_space_bytes)
        )
    except Exception:
        pass


def _run(payload: dict) -> dict:
    """Execute one plan-as-code request against a throwaway, in-memory
    TinyDB built from ``payload``, and return the result.
    """
    code = payload["code"]
    user_request = payload.get("user_request", "")

    db = TinyDB(storage=MemoryStorage)
    inventory_tbl = db.table("inventory")
    transactions_tbl = db.table("transactions")
    if payload.get("inventory_rows"):
        inventory_tbl.insert_multiple(payload["inventory_rows"])
    if payload.get("transaction_rows"):
        transactions_tbl.insert_multiple(payload["transaction_rows"])

    namespace = build_sandbox_namespace(
        db=db,
        inventory_tbl=inventory_tbl,
        transactions_tbl=transactions_tbl,
        user_request=user_request,
    )

    # Capture stdout so generated code's print()s become "plan logs"
    # instead of leaking into this process's real stdout.
    stdout_buffer, real_stdout = io.StringIO(), sys.stdout
    sys.stdout = stdout_buffer
    error_text = None
    try:
        exec(code, namespace)  # noqa: S102 - the whole point of this module
    except Exception:
        error_text = traceback.format_exc()
    finally:
        sys.stdout = real_stdout

    return {
        "stdout": stdout_buffer.getvalue().strip(),
        "error": error_text,
        "answer": (
            namespace.get("answer_text")
            or namespace.get("answer_rows")
            or namespace.get("answer_json")
        ),
        "status": namespace.get("STATUS"),
        "inventory_after": inventory_tbl.all(),
        "transactions_after": transactions_tbl.all(),
    }


def main() -> None:
    """Read one request from stdin, write one JSON result to stdout."""
    _apply_resource_limits()
    payload = json.loads(sys.stdin.read())
    result = _run(payload)
    # default=str: safety net for a non-JSON-serializable value in a row.
    sys.stdout.write(json.dumps(result, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Failure outside _run()'s own try/except (e.g. bad stdin). Still
        # emit valid JSON so executor.py has something to parse.
        sys.stdout.write(
            json.dumps(
                {
                    "stdout": "",
                    "error": traceback.format_exc(),
                    "answer": None,
                    "status": "sandbox_worker_error",
                    "inventory_after": [],
                    "transactions_after": [],
                }
            )
        )
        sys.exit(1)

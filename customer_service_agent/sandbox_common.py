"""Sandbox building blocks: restricted builtins/imports and namespace
construction for executing untrusted, LLM-generated code.
"""

from __future__ import annotations

import re
from typing import Any

from tinydb import Query
from tinydb.table import Table

_EXECUTE_BLOCK_RE = re.compile(
    r"<execute_python>(.*?)</execute_python>", re.DOTALL | re.IGNORECASE
)

# Modules generated code may `import`. No os/subprocess/socket/pathlib/etc.
# This alone does not make the sandbox secure -- see executor.py.
_ALLOWED_MODULES = {
    "re",
    "math",
    "json",
    "itertools",
    "collections",
    "string",
    "statistics",
    "decimal",
    "datetime",
    "tinydb",
}

# Safe builtins for generated code. No open/eval/exec/input/globals/locals;
# __import__ is overridden below with _safe_import.
_SAFE_BUILTIN_NAMES = {
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
    "format", "frozenset", "int", "isinstance", "issubclass", "len", "list",
    "map", "max", "min", "print", "range", "repr", "reversed", "round",
    "set", "sorted", "str", "sum", "tuple", "type", "zip",
    "True", "False", "None",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "StopIteration", "RuntimeError", "ZeroDivisionError", "AttributeError",
    "ArithmeticError", "LookupError",
}


class SandboxImportError(ImportError):
    """Raised when generated code imports a module outside _ALLOWED_MODULES."""


def _safe_import(name: str, *args: Any, **kwargs: Any):
    """Replacement for __import__ that enforces _ALLOWED_MODULES."""
    root = name.split(".")[0]
    if root not in _ALLOWED_MODULES:
        raise SandboxImportError(
            f"Import of module '{name}' is not permitted in generated code."
        )
    return __import__(name, *args, **kwargs)


def build_safe_builtins() -> dict[str, Any]:
    """Build the restricted __builtins__ mapping passed to exec()."""
    import builtins as _builtins

    safe = {
        name: getattr(_builtins, name)
        for name in _SAFE_BUILTIN_NAMES
        if hasattr(_builtins, name)
    }
    safe["__import__"] = _safe_import
    return safe


def extract_execute_block(text: str) -> str:
    """Return the code inside <execute_python>...</execute_python>, or
    ``text`` itself if no tags are found.
    """
    if not text:
        raise RuntimeError("Empty content passed to code executor.")
    match = _EXECUTE_BLOCK_RE.search(text)
    return match.group(1).strip() if match else text.strip()


def _max_transaction_number(transactions_tbl: Table, prefix: str) -> int:
    """Highest numeric suffix among ids matching ``prefix`` (0 if none)."""
    max_num = 0
    for row in transactions_tbl.all():
        tid = str(row.get("transaction_id", ""))
        if tid.startswith(prefix) and tid[len(prefix):].isdigit():
            max_num = max(max_num, int(tid[len(prefix):]))
    return max_num


def get_current_balance(transactions_tbl: Table, default: float = 0.0) -> float:
    """Balance after the most recently inserted transaction, or ``default``
    if the table is empty.
    """
    txns = transactions_tbl.all()
    return txns[-1].get("balance_after_transaction", default) if txns else default


def next_transaction_id(transactions_tbl: Table, prefix: str = "TXN") -> str:
    """Next transaction id, derived from the highest existing numeric suffix.

    Calling this repeatedly without inserting in between returns the SAME
    id each time. To generate several ids before inserting any of them, use
    make_transaction_id_sequence() instead.
    """
    return f"{prefix}{_max_transaction_number(transactions_tbl, prefix) + 1:03d}"


def make_transaction_id_sequence(transactions_tbl: Table):
    """Build a next_transaction_id(tbl=..., prefix="TXN") callable whose
    counter is seeded once from the table and then increments in memory, so
    repeated calls never collide even without inserting in between.
    """
    counters: dict[str, int] = {}

    def _next(tbl: Table = transactions_tbl, prefix: str = "TXN") -> str:
        if prefix not in counters:
            counters[prefix] = _max_transaction_number(tbl, prefix)
        counters[prefix] += 1
        return f"{prefix}{counters[prefix]:03d}"

    return _next


def build_sandbox_namespace(
    *,
    db: Any,
    inventory_tbl: Table,
    transactions_tbl: Table,
    user_request: str,
) -> dict[str, Any]:
    """Build the exec() namespace exposed to generated code.

    Uses one dict for both globals and locals: with two separate dicts,
    exec() treats the code like a class body, breaking lambdas that close
    over top-level variables (e.g. Query().test(lambda v: keyword in v)).
    """
    return {
        "__builtins__": build_safe_builtins(),
        "Query": Query,
        "get_current_balance": get_current_balance,
        "next_transaction_id": make_transaction_id_sequence(transactions_tbl),
        "user_request": user_request or "",
        "db": db,
        "inventory_tbl": inventory_tbl,
        "transactions_tbl": transactions_tbl,
    }

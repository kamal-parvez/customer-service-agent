"""Tests for executor.py: query/mutation execution, sandbox defenses, and
specific regressions found during manual testing.
"""

import pytest
from tinydb import Query

from customer_service_agent.executor import execute_generated_code, extract_execute_block


def test_extract_execute_block_pulls_out_tagged_code():
    content = "some preamble\n<execute_python>\nx = 1\n</execute_python>\ntrailing"
    assert extract_execute_block(content) == "x = 1"


def test_extract_execute_block_returns_raw_code_when_untagged():
    assert extract_execute_block("x = 1") == "x = 1"


def test_extract_execute_block_raises_on_empty_input():
    with pytest.raises(RuntimeError):
        extract_execute_block("")


def test_execute_generated_code_sets_answer_text(store):
    _, inventory_tbl, transactions_tbl = store
    code = """
<execute_python>
# 1) trivial read-only plan
answer_text = "Hello!"
STATUS = "success"
</execute_python>
"""
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["answer"] == "Hello!"
    assert result["status"] == "success"
    assert result["error"] is None


def test_execute_generated_code_can_query_inventory(store):
    _, inventory_tbl, transactions_tbl = store
    code = """
<execute_python>
item = Query()
rows = inventory_tbl.search(item.name == "Aviator")
answer_text = f"found {len(rows)} row(s)"
STATUS = "success"
</execute_python>
"""
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["answer"] == "found 1 row(s)"


def test_execute_generated_code_can_mutate_inventory(store):
    _, inventory_tbl, transactions_tbl = store
    item = Query()
    before = inventory_tbl.get(item.name == "Aviator")["quantity_in_stock"]

    code = f"""
<execute_python>
item = Query()
inventory_tbl.update({{"quantity_in_stock": {before + 2}}}, item.name == "Aviator")
answer_text = "updated"
STATUS = "success"
</execute_python>
"""
    execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    after = inventory_tbl.get(item.name == "Aviator")["quantity_in_stock"]
    assert after == before + 2


def test_execute_generated_code_allows_reimporting_tinydb(store):
    _, inventory_tbl, transactions_tbl = store
    code = """
<execute_python>
from tinydb import Query
item = Query()
rows = inventory_tbl.search(item.name == "Aviator")
answer_text = f"found {len(rows)} row(s)"
STATUS = "success"
</execute_python>
"""
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["error"] is None
    assert result["answer"] == "found 1 row(s)"


def test_execute_generated_code_supports_closures_over_local_vars(store):
    """Regression: a lambda closing over a local var (e.g. Query().test(lambda
    v: keyword in v)) must not raise NameError -- see build_sandbox_namespace.
    """
    _, inventory_tbl, transactions_tbl = store
    code = """
<execute_python>
item = Query()
keyword = "aviator"
rows = inventory_tbl.search(item.name.test(lambda v: keyword.lower() in v.lower()))
answer_text = f"found {len(rows)} row(s)"
STATUS = "success"
</execute_python>
"""
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["error"] is None
    assert result["answer"] == "found 1 row(s)"


def test_execute_generated_code_captures_errors(store):
    _, inventory_tbl, transactions_tbl = store
    code = "<execute_python>\n1 / 0\n</execute_python>"
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["error"] is not None
    assert "ZeroDivisionError" in result["error"]


def test_execute_generated_code_blocks_disallowed_imports(store):
    _, inventory_tbl, transactions_tbl = store
    code = "<execute_python>\nimport os\nanswer_text = os.getcwd()\n</execute_python>"
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["error"] is not None
    assert "not permitted" in result["error"]


def test_execute_generated_code_blocks_open(store):
    _, inventory_tbl, transactions_tbl = store
    code = "<execute_python>\nopen('/etc/passwd')\n</execute_python>"
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["error"] is not None
    assert "NameError" in result["error"]


def test_execute_generated_code_does_not_duplicate_transaction_ids(store):
    """Regression: computing several transaction ids before inserting any
    of them (a natural pattern for "one row per item") must not collide.
    """
    _, inventory_tbl, transactions_tbl = store
    code = """
<execute_python>
items = ["Aviator", "Wayfarer"]
new_rows = []
for name in items:
    txn_id = next_transaction_id(transactions_tbl)  # computed before any insert
    new_rows.append({
        "transaction_id": txn_id,
        "customer_name": "WALK_IN",
        "transaction_summary": name,
        "transaction_amount": 1.0,
        "balance_after_transaction": 1.0,
    })
transactions_tbl.insert_multiple(new_rows)
answer_text = "done"
STATUS = "success"
</execute_python>
"""
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["error"] is None
    ids = [row["transaction_id"] for row in result["transactions_after"]]
    assert len(ids) == len(set(ids)), f"duplicate transaction ids: {ids}"


def test_execute_generated_code_reports_missing_answer_text(store):
    """A clean run with no answer_text set returns answer=None (agent.py
    is responsible for the user-facing fallback).
    """
    _, inventory_tbl, transactions_tbl = store
    code = """
<execute_python>
rows = inventory_tbl.search(Query().name == "Aviator")
STATUS = "success"
</execute_python>
"""
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["error"] is None
    assert result["answer"] is None  # agent.py is responsible for the fallback


def test_execute_generated_code_enforces_timeout(store, monkeypatch):
    monkeypatch.setenv("EXECUTOR_TIMEOUT_SECONDS", "1")
    _, inventory_tbl, transactions_tbl = store
    code = "<execute_python>\nwhile True:\n    pass\n</execute_python>"
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert result["status"] == "execution_timeout"
    assert result["error"] is not None


def test_sandboxed_code_cannot_see_parent_secrets(store, monkeypatch):
    """A secret in the parent's env must stay invisible to sandboxed code,
    even when it uses the object-introspection escape to spawn Popen.
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "totally-secret-value")
    _, inventory_tbl, transactions_tbl = store
    code = """
<execute_python>
Popen = [c for c in ().__class__.__base__.__subclasses__() if c.__name__ == "Popen"][0]
p = Popen(["env"], stdout=-1)
out, _ = p.communicate()
answer_text = out.decode()
STATUS = "success"
</execute_python>
"""
    result = execute_generated_code(
        code, inventory_tbl=inventory_tbl, transactions_tbl=transactions_tbl
    )
    assert "totally-secret-value" not in (result["answer"] or "")

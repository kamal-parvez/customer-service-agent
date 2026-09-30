"""Tests for the seeding, balance/id helpers, and schema-block builder in db.py."""

from customer_service_agent.db import (
    SUNGLASSES_DATA,
    build_schema_block,
    get_current_balance,
    next_transaction_id,
)


def test_create_inventory_seeds_all_items(store):
    _, inventory_tbl, _ = store
    assert len(inventory_tbl) == len(SUNGLASSES_DATA)
    names = {row["name"] for row in inventory_tbl.all()}
    assert names == {item["name"] for item in SUNGLASSES_DATA}


def test_create_transactions_seeds_opening_balance(store):
    _, _, transactions_tbl = store
    rows = transactions_tbl.all()
    assert len(rows) == 1
    assert rows[0]["customer_name"] == "OPENING_BALANCE"
    assert rows[0]["balance_after_transaction"] == 500.00


def test_get_current_balance_tracks_last_row(store):
    _, _, transactions_tbl = store
    assert get_current_balance(transactions_tbl) == 500.00
    transactions_tbl.insert(
        {
            "transaction_id": "TXN002",
            "customer_name": "Alice",
            "transaction_summary": "Purchase 1 Aviator",
            "transaction_amount": -80.0,
            "balance_after_transaction": 420.0,
        }
    )
    assert get_current_balance(transactions_tbl) == 420.0


def test_next_transaction_id_increments(store):
    _, _, transactions_tbl = store
    assert next_transaction_id(transactions_tbl) == "TXN002"


def test_build_schema_block_mentions_both_tables(store):
    _, inventory_tbl, transactions_tbl = store
    schema = build_schema_block(inventory_tbl, transactions_tbl)
    assert "TABLE: inventory_tbl" in schema
    assert "TABLE: transactions_tbl" in schema
    assert "quantity_in_stock" in schema

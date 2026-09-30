"""Shared pytest fixtures for the test suite."""

import pytest
from tinydb import TinyDB
from tinydb.storages import MemoryStorage

from customer_service_agent.db import create_inventory, create_transactions


@pytest.fixture()
def store():
    """A fresh, seeded, in-memory TinyDB store: (db, inventory_tbl, transactions_tbl)."""
    db = TinyDB(storage=MemoryStorage)
    inventory_tbl = db.table("inventory")
    transactions_tbl = db.table("transactions")
    create_inventory(inventory_tbl)
    create_transactions(transactions_tbl)
    return db, inventory_tbl, transactions_tbl

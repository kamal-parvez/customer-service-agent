"""TinyDB-backed inventory & transactions store for the sunglasses shop.

Seeds the demo catalog, opens the on-disk TinyDB store, and builds the
schema text embedded in the LLM prompt (see prompts.py).

get_current_balance/next_transaction_id are re-exported from
sandbox_common.py (which has no config.py dependency) so they're still
importable from here for app-level code and tests.
"""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path
from typing import Any

from tinydb import TinyDB
from tinydb.table import Table

from customer_service_agent.config import settings
from customer_service_agent.sandbox_common import (
    get_current_balance,
    next_transaction_id,
)

__all__ = [
    "SUNGLASSES_DATA",
    "open_db",
    "create_inventory",
    "create_transactions",
    "seed_db",
    "get_or_create_db",
    "build_schema_for_table",
    "build_schema_block",
    "get_current_balance",
    "next_transaction_id",
]

# Static demo catalog; create_inventory() adds a randomized quantity_in_stock.
SUNGLASSES_DATA: list[dict[str, Any]] = [
    {
        "item_id": "SG001",
        "name": "Aviator",
        "description": (
            "Originally designed for pilots, these teardrop-shaped lenses with "
            "thin metal frames offer timeless appeal. The large lenses provide "
            "excellent coverage while the lightweight construction ensures "
            "comfort during long wear."
        ),
        "price": 80,
    },
    {
        "item_id": "SG002",
        "name": "Wayfarer",
        "description": (
            "Featuring thick, angular frames that make a statement, these "
            "sunglasses combine retro charm with modern edge. The rectangular "
            "lenses and sturdy acetate construction create a confident look."
        ),
        "price": 95,
    },
    {
        "item_id": "SG003",
        "name": "Mystique",
        "description": (
            "Inspired by 1950s glamour, these frames sweep upward at the outer "
            "corners to create an elegant, feminine silhouette. The subtle "
            "curves and often embellished temples add sophistication to any "
            "outfit."
        ),
        "price": 70,
    },
    {
        "item_id": "SG004",
        "name": "Sport",
        "description": (
            "Designed for active lifestyles, these wraparound sunglasses "
            "feature a single curved lens that provides maximum coverage and "
            "wind protection. The lightweight, flexible frames include rubber "
            "grips."
        ),
        "price": 110,
    },
    {
        "item_id": "SG005",
        "name": "Classic",
        "description": (
            "Classic round profile with minimalist metal frames, offering a "
            "timeless and versatile style that fits both casual and formal "
            "wear."
        ),
        "price": 60,
    },
    {
        "item_id": "SG006",
        "name": "Moon",
        "description": (
            "Oversized round style with bold plastic frames, evoking retro "
            "aesthetics with a modern twist."
        ),
        "price": 120,
    },
]


def open_db(db_path: Path | str | None = None) -> TinyDB:
    """Open the TinyDB store at db_path (default: settings.db_path),
    creating the file/parent directory if needed.
    """
    path = Path(db_path) if db_path is not None else settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(path)


def create_inventory(inventory_tbl: Table, seed: int = 42) -> list[dict[str, Any]]:
    """(Re)populate inventory_tbl with the demo catalog. Destructive."""
    random.seed(seed)  # fixed so reseeded demo stock levels are reproducible
    rows = [
        {**item, "quantity_in_stock": random.randint(3, 25)}
        for item in SUNGLASSES_DATA
    ]
    inventory_tbl.truncate()
    inventory_tbl.insert_multiple(rows)
    return rows


def create_transactions(
    transactions_tbl: Table, opening_balance: float = 500.00
) -> dict[str, Any]:
    """Reset transactions_tbl to a single opening-balance row. Destructive."""
    opening_transaction = {
        "transaction_id": "TXN001",
        "customer_name": "OPENING_BALANCE",
        "transaction_summary": "Daily opening register balance",
        "transaction_amount": opening_balance,
        "balance_after_transaction": opening_balance,
        "timestamp": datetime.now().isoformat(),
    }
    transactions_tbl.truncate()
    transactions_tbl.insert(opening_transaction)
    return opening_transaction


def seed_db(
    db_path: Path | str | None = None,
) -> tuple[TinyDB, Table, Table]:
    """Open the store and unconditionally (re)seed both tables (fresh demo run)."""
    db = open_db(db_path)
    inventory_tbl = db.table("inventory")
    transactions_tbl = db.table("transactions")
    create_inventory(inventory_tbl)
    create_transactions(transactions_tbl)
    return db, inventory_tbl, transactions_tbl


def get_or_create_db(
    db_path: Path | str | None = None,
) -> tuple[TinyDB, Table, Table]:
    """Open the store, seeding only if empty. Use for normal app startup so
    existing state survives across runs; use seed_db() to force a reset.
    """
    db = open_db(db_path)
    inventory_tbl = db.table("inventory")
    transactions_tbl = db.table("transactions")
    if len(inventory_tbl) == 0:
        create_inventory(inventory_tbl)
    if len(transactions_tbl) == 0:
        create_transactions(transactions_tbl)
    return db, inventory_tbl, transactions_tbl


# ==== Schema helpers: build the text description embedded in the LLM prompt ====


def _infer_type(value: Any) -> str:
    """Map a Python value to the short type label used in the schema block."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "string"


def build_schema_for_table(tbl: Table, table_name: str, k: int = 3) -> str:
    """Render one table's columns/types/example values as plain text."""
    rows = tbl.all()
    if not rows:
        return f"TABLE: {table_name} (empty)"

    schema: dict[str, dict[str, Any]] = {}
    for row in rows:
        for col, value in row.items():
            info = schema.setdefault(
                col, {"type": _infer_type(value), "examples": []}
            )
            if len(info["examples"]) < k and str(value) not in info["examples"]:
                info["examples"].append(str(value))

    lines = [f"TABLE: {table_name}", "COLUMNS:"]
    for col, info in schema.items():
        examples = f" | examples: {info['examples']}" if info["examples"] else ""
        lines.append(f"  - {col}: {info['type']}{examples}")
    lines.append(f"ROWS: {len(rows)}")
    lines.append(f"PREVIEW (first 3 rows): {rows[:3]}")
    return "\n".join(lines)


def build_schema_block(inventory_tbl: Table, transactions_tbl: Table) -> str:
    """Build the full schema text substituted into PLAN_AS_CODE_PROMPT."""
    inv = build_schema_for_table(inventory_tbl, "inventory_tbl")
    tx = build_schema_for_table(transactions_tbl, "transactions_tbl")
    notes = (
        "NOTES:\n"
        "- inventory_tbl.price is in USD.\n"
        "- inventory_tbl.quantity_in_stock > 0 means available stock.\n"
        "- inventory_tbl.name describes the style (e.g., 'Classic', 'Moon').\n"
        "- transactions_tbl.timestamp is ISO-8601.\n"
    )
    return f"{inv}\n\n{tx}\n\n{notes}"

"""Interactive CLI chat loop for the customer service agent."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence

from customer_service_agent.agent import customer_service_agent
from customer_service_agent.config import settings
from customer_service_agent.db import get_or_create_db, seed_db
from customer_service_agent.llm import LLMConfigError

logger = logging.getLogger(__name__)

HELP_TEXT = """\
Commands:
  :help          show this message
  :inventory     print the current inventory table
  :transactions  print the current transactions log
  :reseed        reset inventory & transactions to the default demo data
  :verbose       toggle showing the generated code + execution logs
  :quit / :exit  leave the chat

Anything else is treated as a customer request, e.g.:
  "Do you have any round sunglasses in stock that are under $100?"
  "Return 2 Aviator sunglasses."
  "I want to buy 3 pairs of classic sunglasses and 1 pair of aviator."
"""


def _print_table(rows: Sequence[dict]) -> None:
    """Pretty-print rows as indented JSON."""
    print(json.dumps(rows, indent=2))


def run(reseed: bool, model: str | None) -> None:
    """Run the interactive chat loop until the user quits or sends EOF."""
    db, inventory_tbl, transactions_tbl = (
        seed_db() if reseed else get_or_create_db()
    )

    verbose = False
    print("Sunglasses store customer service agent. Type :help for commands.\n")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input in (":quit", ":exit"):
            break
        if user_input == ":help":
            print(HELP_TEXT)
            continue
        if user_input == ":inventory":
            _print_table(inventory_tbl.all())
            continue
        if user_input == ":transactions":
            _print_table(transactions_tbl.all())
            continue
        if user_input == ":reseed":
            # Local import: only this rarely-used command needs it.
            from customer_service_agent.db import create_inventory, create_transactions

            create_inventory(inventory_tbl)
            create_transactions(transactions_tbl)
            print("Inventory and transactions reset to defaults.")
            continue
        if user_input == ":verbose":
            verbose = not verbose
            print(f"verbose mode: {'on' if verbose else 'off'}")
            continue

        try:
            result = customer_service_agent(
                user_input,
                inventory_tbl=inventory_tbl,
                transactions_tbl=transactions_tbl,
                model=model,
            )
        except LLMConfigError as exc:
            print(f"agent> [config error] {exc}")
            continue
        except Exception:
            # Safety net: never let one bad turn kill the whole session.
            logger.exception("unexpected error handling request: %r", user_input)
            print("agent> Sorry, something unexpected went wrong. Please try again.")
            continue

        if verbose:
            print("\n--- generated code ---")
            print(result["code"])
            if result["stdout"]:
                print("\n--- plan logs ---")
                print(result["stdout"])
            if result["error"]:
                print("\n--- execution error ---")
                print(result["error"])
            print("---\n")

        print(f"agent> {result['answer']}")


def main() -> None:
    """CLI entry point: parse args and start the chat loop."""
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="reset inventory & transactions to default demo data on startup",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Gemini model to use (default: {settings.gemini_model})",
    )
    args = parser.parse_args()

    run(reseed=args.reseed, model=args.model)


if __name__ == "__main__":
    main()

# Sunglasses Store Customer Service Agent

A small "code-as-plan" agentic workflow: a customer's natural-language
request (buy, return, browse, ask a question) is turned into **Python code
written by an LLM**, which is then executed against a TinyDB-backed
inventory and transaction ledger.


## How it works

1. **Schema block** — `db.py` builds a short text description of the
   `inventory_tbl` and `transactions_tbl` TinyDB tables (columns, types,
   sample rows) so the model knows what data it can work with.
2. **Plan-as-code prompt** — `prompts.py` asks the model to respond with a
   `<execute_python>...</execute_python>` block: real Python that reads or
   mutates the tables, using the model's own reasoning instead of a fixed
   menu of tools.
3. **Generation** — `llm.py` sends that prompt to Gemini and returns the raw
   response text (no execution yet).
4. **Execution** — `executor.py` extracts the code block and runs it in an
   isolated subprocess (`sandbox_worker.py`): a restricted namespace (only
   the TinyDB tables, a `Query` class, two helper functions, and a small
   allow-listed set of builtins/imports), a stripped environment with no
   API keys, a wall-clock timeout, and best-effort CPU/memory limits.
5. **Orchestration** — `agent.py`'s `customer_service_agent()` wires steps
   3-4 together and returns the generated code, any stdout logs, the
   execution error (if any), a machine-readable `STATUS`, and the
   customer-facing `answer_text`.
6. **CLI** — `cli.py` / `main.py` give you an interactive chat loop over all
   of the above.

## Project layout

```
customer_service_agent/
  config.py         # env var loading (API keys, model name, DB path)
  db.py             # TinyDB seeding + schema-block builder (app-level; may read .env)
  sandbox_common.py # sandbox namespace/builtins/import allow-list -- NO dependency on config.py
  sandbox_worker.py # subprocess entry point that actually exec()s generated code
  prompts.py        # the plan-as-code prompt template
  llm.py            # Gemini API call
  executor.py       # spawns sandbox_worker.py, reconciles the real tables with its result
  agent.py          # orchestrates llm.py + executor.py, guarantees a user-facing answer
  cli.py            # interactive terminal chat loop
tests/              # pytest suite (db, executor, agent) using an in-memory TinyDB
data/           # runtime TinyDB JSON store (gitignored)
Study/          # original course notebooks/scripts this project is based on
main.py         # `python main.py` entry point
```

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes requirements.txt + pytest

cp .env.example .env
# then edit .env and set GOOGLE_API_KEY
```


## Running

```bash
python main.py
```

On first run it seeds `data/store_db.json` with a demo sunglasses catalog
and a $500 opening balance, then drops you into a chat loop:

```
you> Do you have any round sunglasses in stock that are under $100?
agent> Yes, we have our Classic sunglasses, a round frame, for $60.

you> Return 2 Aviator sunglasses.
agent> Got it - I've processed a return for 2 Aviator sunglasses and updated your balance.
```

In-chat commands: `:help`, `:inventory`, `:transactions`, `:reseed`,
`:verbose` (show the generated code + logs for each turn), `:quit`.








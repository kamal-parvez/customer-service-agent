"""Application configuration, loaded once from the environment.

Not imported by the sandbox worker (see sandbox_common.py) -- doing so
would pull in load_dotenv() and leak secrets into the sandboxed subprocess.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "store_db.json"


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, read from environment variables."""

    google_api_key: str | None
    gemini_model: str
    temperature: float
    tavily_api_key: str | None  # reserved for a future web-search fallback; unused today
    db_path: Path


def load_settings() -> Settings:
    """Build a Settings instance from the current environment."""
    return Settings(
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.2")),
        tavily_api_key=os.getenv("TAVILY_API_KEY"),
        db_path=Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH))),
    )


# Loaded once at import time; restart the process to pick up .env changes.
settings = load_settings()

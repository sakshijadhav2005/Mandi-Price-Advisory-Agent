"""Start the real backend for the Playwright end-to-end tests.

Uses its own SQLite file with synthetic prices ending on a fixed date, the offline
answer writer (no API keys, deterministic answers) and no login, so the tests
are repeatable. Called by playwright.config.ts; not meant for normal use.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend"
DB = BACKEND / "e2e.db"
PORT = os.environ.get("E2E_API_PORT", "8010")
WEB_ORIGIN = os.environ.get("E2E_WEB_ORIGIN", "http://localhost:5174")

env = {
    **os.environ,
    "DATABASE_URL": f"sqlite:///{DB.as_posix()}",
    "AS_OF_OVERRIDE": "2026-11-08",
    "LLM_ENABLED": "false",
    "AUTH_REQUIRED": "false",
    "STT_PROVIDER": "none",
    "TTS_PROVIDER": "none",
    "CORS_ORIGINS": f"{WEB_ORIGIN},http://127.0.0.1:{WEB_ORIGIN.rsplit(':', 1)[-1]}",
}

DB.unlink(missing_ok=True)
subprocess.run([sys.executable, "manage.py", "seed-synthetic", "--days", "400", "--end", "2026-11-08"], cwd=BACKEND, env=env, check=True)
sys.exit(subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--port", PORT], cwd=BACKEND, env=env).returncode)

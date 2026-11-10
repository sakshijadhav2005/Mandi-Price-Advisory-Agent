import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="mandi-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["AS_OF_OVERRIDE"] = "2026-11-08"
os.environ["LLM_ENABLED"] = "false"
os.environ["LLM_PROVIDER"] = "anthropic"  # tests that enable the LLM use a fake Claude client
os.environ["AUTH_REQUIRED"] = "false"

import pytest  # noqa: E402

from app.db.session import init_db, session_scope  # noqa: E402
from app.ingestion.prices import bulk_insert_prices  # noqa: E402
from app.ingestion.synthetic import generate  # noqa: E402

AS_OF = date(2026, 11, 8)


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    init_db()
    with session_scope() as s:
        bulk_insert_prices(s, generate(AS_OF - timedelta(days=120), AS_OF), "synthetic")
    yield


@pytest.fixture
def session():
    with session_scope() as s:
        yield s

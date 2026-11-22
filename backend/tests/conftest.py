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
# Tests start from the defaults, whatever the developer's backend/.env switches on
# (environment variables take precedence over .env).
for _name, _value in {
    "LOCKED_DISTRICT": "",
    "ADMIN_TOKEN": "",
    "RATE_LIMIT_BACKEND": "memory",
    "TTS_PROVIDER": "none",
    "STT_PROVIDER": "none",
    "SARVAM_API_KEY": "",
    "GOOGLE_CLIENT_ID": "",
    "GOOGLE_EXTRA_CLIENT_IDS": "",
    "AGROMET_DISTRICTS": "pune",
    "KCC_DISTRICTS": "pune",
    "KCC_RESOURCE_ID": "",
    "OTP_DEV_MODE": "true",
    "DEMO_PRICES": "true",
    "DATA_GOV_IN_API_KEY": "",
}.items():
    os.environ[_name] = _value

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


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Each test starts with empty login / OTP / signup counters."""
    from app.api import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()


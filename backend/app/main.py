from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.data import today
from app.agent.service import resolve_provider
from app.api import admin, alerts, auth, chat, prices, voice
from app.config import get_settings
from app.db.retention import purge_old_history
from app.db.session import init_db, session_scope
from app.reference import load_reference
from app.retrieval.index import get_index
from app.translation.languages import load_languages
from app.voice.adapters import capabilities

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if get_settings().sentry_dsn:
    try:
        import sentry_sdk  # type: ignore

        sentry_sdk.init(dsn=get_settings().sentry_dsn, traces_sample_rate=0.1, send_default_pii=False)
    except ImportError:
        logging.getLogger(__name__).warning("SENTRY_DSN is set but sentry-sdk is not installed")


def _retention_loop(stop: threading.Event) -> None:
    """Delete chat history older than HISTORY_RETENTION_DAYS now, then every hour."""
    while True:
        try:
            with session_scope() as s:
                purge_old_history(s)
        except Exception:  # never let a cleanup error kill the thread
            logging.getLogger(__name__).exception("history retention run failed")
        if stop.wait(3600):
            return


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    threading.Thread(target=get_index, daemon=True).start()  # warm the advisory index
    stop = threading.Event()
    threading.Thread(target=_retention_loop, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Mandi Price & Advisory Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(prices.router)
app.include_router(voice.router)
app.include_router(alerts.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/meta")
def meta() -> dict:
    ref = load_reference()
    s = get_settings()
    return {
        "today": today().isoformat(),
        "district": ref.district,
        "districts": [d.as_dict() for d in ref.districts.values()],
        "languages": {code: p.name for code, p in load_languages().items()},
        "language_packs": [{"code": p.code, "name": p.name, "speech_locale": p.speech_locale} for p in load_languages().values()],
        "crops": [{"id": c.id, "name": c.name, "names": c.names} for c in ref.crops.values()],
        "markets": [
            {"id": m.id, "name": m.name, "names": m.names, "lat": m.lat, "lon": m.lon, "district": m.district}
            for m in ref.markets.values()
        ],
        "voice": capabilities(),
        "answer_writer": resolve_provider(),
        "auth_required": s.auth_required,
        "google_client_id": s.google_client_id or None,  # public value; the web app shows "Sign in with Google" when set
        "stale_after_days": s.stale_after_days,
    }

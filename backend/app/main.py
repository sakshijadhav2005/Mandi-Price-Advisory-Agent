from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.advisory.agromet import purge_old_bulletins
from app.agent.data import today
from app.agent.service import resolve_provider
from app.api import admin, alerts, auth, chat, prices, ratelimit, voice
from app.config import get_settings
from app.db.retention import purge_old_history
from app.db.session import init_db, session_scope
from app.reference import load_reference, locked_district
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
    """Delete chat history older than HISTORY_RETENTION_DAYS and IMD bulletins older than
    AGROMET_RETENTION_DAYS now, then every hour."""
    while True:
        try:
            with session_scope() as s:
                purge_old_history(s)
                purge_old_bulletins(s, today())
                ratelimit.purge_old(s)
        except Exception:  # never let a cleanup error kill the thread
            logging.getLogger(__name__).exception("history retention run failed")
        if stop.wait(3600):
            return


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    stop = threading.Event()
    threading.Thread(target=_retention_loop, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Mandi Price & Advisory Agent", version="0.1.0", lifespan=lifespan)
# /meta lists every district and market in India (~250 KB); gzip makes it ~10x smaller on a slow phone link.
app.add_middleware(GZipMiddleware, minimum_size=1024)
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
    locked = locked_district()
    # A single-district deployment lists only its district, so the apps hide the picker.
    districts = [ref.districts[locked]] if locked else list(ref.districts.values())
    return {
        "today": today().isoformat(),
        "district": locked or ref.district,
        "locked_district": locked,
        "districts": [d.as_dict() for d in districts],
        "states": sorted({d.state for d in districts}),
        "languages": {code: p.name for code, p in load_languages().items()},
        "language_packs": [{"code": p.code, "name": p.name, "speech_locale": p.speech_locale} for p in load_languages().values()],
        "crops": [{"id": c.id, "name": c.name, "names": c.names} for c in ref.crops.values()],
        "markets": [
            {"id": m.id, "name": m.name, "names": m.names, "lat": m.lat, "lon": m.lon, "district": m.district}
            for m in ref.markets.values()
            if not locked or m.district == locked
        ],
        "voice": capabilities(),
        "answer_writer": resolve_provider(),
        "auth_required": s.auth_required,
        "google_client_id": s.google_client_id or None,  # public value; the web app shows "Sign in with Google" when set
        "stale_after_days": s.stale_after_days,
    }

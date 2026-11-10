"""Application settings, loaded from environment variables (or backend/.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Storage
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'mandi.db').as_posix()}"

    # LLM. With no Anthropic credentials the agent falls back to a deterministic,
    # template-based answer writer, so the app and evaluation work offline.
    llm_enabled: bool = True
    # auto: Claude if ANTHROPIC_API_KEY is set, else the offline template writer.
    # A free local model is opt-in with LLM_PROVIDER=ollama. Or force anthropic | none.
    # Values: auto | anthropic | gemini | groq | openrouter | ollama | none.
    # auto order: Claude, then the first free hosted key set (Gemini, Groq, OpenRouter), else templates.
    llm_provider: str = "auto"
    # Free hosted models (OpenAI-compatible APIs)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_s: float = 180.0
    # Languages the local model may answer in; others use the template writer.
    # 3B models write weak Hindi/Marathi. Try "en,hi,mr" with qwen2.5:7b or larger.
    ollama_languages: str = "en"
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "low"  # low | medium | high | xhigh | max
    llm_max_tokens: int = 4000

    # Agent guardrails (plan section 6)
    tool_budget: int = 6
    stale_after_days: int = 3
    min_price_points: int = 5

    # Prices. "today" can be pinned for demos and tests; empty means the real date.
    as_of_override: str = ""
    data_gov_in_api_key: str = ""
    data_gov_in_resource_id: str = "9ef84268-d588-465a-a308-a864a43d0070"

    # Auth
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_hours: int = 24 * 30
    auth_required: bool = False  # dev default: guests may chat without OTP login
    otp_dev_mode: bool = True  # logs the OTP instead of sending an SMS

    # Voice (server-side providers are optional; the web app can use browser speech)
    stt_provider: str = "none"  # none | whisper
    whisper_model: str = "small"
    tts_provider: str = "none"  # none | google | azure
    google_tts_api_key: str = ""
    azure_speech_key: str = ""
    azure_speech_region: str = "centralindia"
    store_voice_recordings: bool = False  # kept only when this is true AND the farmer consented
    recordings_dir: str = ""  # default backend/recordings
    s3_bucket: str = ""  # store consented recordings in S3-compatible storage instead (pip install boto3)
    s3_prefix: str = "voice"
    s3_endpoint_url: str = ""  # for Cloudflare R2, MinIO, etc.
    s3_region: str = ""

    # Retrieval embedder: char (default, no download) | sentence-transformers
    # (pip install sentence-transformers)
    retrieval_embedder: str = "char"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # Operations alerts: a Slack/Discord/Teams-style webhook that receives {"text": ...}
    # when the daily ingestion fails or leaves no fresh prices.
    ops_alert_webhook_url: str = ""

    # Price alerts / push notifications (Expo push service for the mobile app)
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"
    expo_access_token: str = ""
    alert_check_time: str = "19:00"

    # Pilot / admin
    admin_token: str = ""  # enables /admin endpoints when set
    sentry_dsn: str = ""

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,capacitor://localhost,http://localhost"

    @property
    def ollama_language_list(self) -> list[str]:
        return [x.strip() for x in self.ollama_languages.split(",") if x.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

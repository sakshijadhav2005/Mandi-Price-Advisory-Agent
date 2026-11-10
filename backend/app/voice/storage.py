"""Where consented voice recordings go (plan section 8: consent first, delete by default).

A recording is kept only when STORE_VOICE_RECORDINGS=true *and* the farmer ticked
consent for that request. It goes to an S3-compatible bucket when S3_BUCKET is set
(`pip install boto3`; works with AWS S3, Cloudflare R2, MinIO via S3_ENDPOINT_URL),
otherwise to RECORDINGS_DIR on the server's disk. Encrypted at rest on S3 (SSE).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import BACKEND_DIR, get_settings

log = logging.getLogger(__name__)


def should_store(consent: bool) -> bool:
    return bool(consent and get_settings().store_voice_recordings)


def _key(suffix: str, language: str | None) -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y/%m/%d}/{language or 'xx'}-{uuid.uuid4().hex}{suffix}"


def store_recording(audio: bytes, suffix: str, language: str | None) -> str:
    """Save one consented recording. Returns its location (s3://... or a file path)."""
    s = get_settings()
    key = _key(suffix if suffix.startswith(".") else f".{suffix}", language)
    if s.s3_bucket:
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError("S3_BUCKET is set but boto3 is not installed (pip install boto3)") from exc
        client = boto3.client("s3", endpoint_url=s.s3_endpoint_url or None, region_name=s.s3_region or None)
        full_key = f"{s.s3_prefix.strip('/')}/{key}" if s.s3_prefix else key
        client.put_object(Bucket=s.s3_bucket, Key=full_key, Body=audio, ServerSideEncryption="AES256")
        return f"s3://{s.s3_bucket}/{full_key}"
    root = Path(s.recordings_dir) if s.recordings_dir else BACKEND_DIR / "recordings"
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return str(path)

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.auth import Identity, get_identity
from app.voice import adapters

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # ~5 min of Opus


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str | None = Form(default=None),
    consent: bool = Form(default=False),  # farmer agreed to keep this recording
    _identity: Identity = Depends(get_identity),
) -> dict:
    data = await audio.read()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio too long")
    suffix = "." + (audio.filename or "audio.webm").rsplit(".", 1)[-1]
    try:
        tr = adapters.transcribe(data, suffix=suffix, language_hint=language, consent=consent)
    except adapters.VoiceNotConfigured as exc:
        raise HTTPException(501, str(exc))
    return {"text": tr.text, "language": tr.language, "confidence": tr.confidence, "needs_confirmation": tr.needs_confirmation}


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    language: str = "en"


@router.post("/speak")
def speak(body: SpeakRequest, _identity: Identity = Depends(get_identity)) -> Response:
    try:
        audio, media_type = adapters.synthesize(body.text, body.language)
    except adapters.VoiceNotConfigured as exc:
        raise HTTPException(501, str(exc))
    except adapters.VoiceProviderError as exc:
        raise HTTPException(502, str(exc))
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})

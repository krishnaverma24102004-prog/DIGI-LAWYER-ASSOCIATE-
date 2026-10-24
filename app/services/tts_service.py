"""Talking mode: the agent's reply as natural speech (Deepgram Aura text-to-speech).

Two output shapes:
  * synthesize(text, encoding="mp3")   one playable buffer, sent to WebSocket clients
  * stream_speech(text)                raw 48 kHz 16-bit mono PCM chunks as Deepgram produces
                                       them, fed straight into the WebRTC audio track so
                                       playback starts before synthesis finishes

Before speaking, text is made speakable: PII placeholders become natural phrases ("the
account number you mentioned") rather than being read out or unmasked, the long written
disclaimer becomes a short spoken one, citations are named rather than recited ("the relevant
provision": section numbers and case reports are for reading and checking, not listening), and
markdown/URLs are dropped.

Deepgram receives only the agent's reply, which was generated from masked text.
"""

import inspect
import io
import re
import wave
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings
from app.core.guardrails import LEGAL_DISCLAIMER
from app.services import citation_service

MAX_TTS_CHARS = 1900  # Deepgram Aura accepts up to 2000 characters per request
SPOKEN_DISCLAIMER = "This is general legal information, not legal advice, and a licensed attorney should review it."

PLACEHOLDER_PHRASES = {
    "CLIENT_SSN": "the Social Security number you mentioned",
    "TAX_ID": "the tax ID you mentioned",
    "CARD_NUMBER": "the card you mentioned",
    "BANK_ACCT": "the bank account you mentioned",
    "NATIONAL_ID": "the ID number you mentioned",
    "PASSPORT_NO": "the passport number you mentioned",
    "DRIVER_LICENSE": "the driving licence you mentioned",
    "VOTER_ID": "the voter ID you mentioned",
    "CRYPTO_WALLET": "the crypto wallet you mentioned",
    "EMAIL": "the email address you mentioned",
    "PHONE": "the phone number you mentioned",
    "IP_ADDRESS": "the IP address you mentioned",
}
_PLACEHOLDER = re.compile(r"\[([A-Z_]+?)(?:_\d+)?\]")


class TTSError(RuntimeError):
    pass


def is_configured() -> bool:
    settings = get_settings()
    return settings.tts_enabled and bool(settings.deepgram_api_key)


def speakable(text: str) -> str:
    """Text as it should be read aloud."""
    text = text.replace(LEGAL_DISCLAIMER, SPOKEN_DISCLAIMER)
    text = citation_service.spoken(text) or ""
    def phrase(match: re.Match) -> str:
        spoken = PLACEHOLDER_PHRASES.get(match.group(1), "the detail you mentioned")
        before = text[: match.start()].rstrip()
        return spoken[0].upper() + spoken[1:] if not before or before[-1] in ".!?" else spoken

    text = _PLACEHOLDER.sub(phrase, text)
    text = re.sub(r"https?://\S+", "", text)  # URLs are for reading, not listening
    text = re.sub(r"[*_#`>|]+", "", text)  # markdown
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_TTS_CHARS:
        cut = text[:MAX_TTS_CHARS]
        text = cut[: cut.rfind(". ") + 1] or cut
    return text


# One HTTP client for all replies: reusing its connection to Deepgram saves the TLS handshake on
# every reply (measured ~0.5-1.5 s of the time before the first audio on a phone call).
_shared_http: httpx.AsyncClient | None = None


def _client(http_client: httpx.AsyncClient | None = None):
    from deepgram import AsyncDeepgramClient

    global _shared_http
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise TTSError("DEEPGRAM_API_KEY is not set")
    if http_client is None:
        if _shared_http is None or _shared_http.is_closed:
            _shared_http = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10))
        http_client = _shared_http
    return AsyncDeepgramClient(api_key=settings.deepgram_api_key, httpx_client=http_client)


async def close_client() -> None:
    global _shared_http
    if _shared_http is not None:
        await _shared_http.aclose()
        _shared_http = None


async def _chunks(
    text: str, *, encoding: str, sample_rate: int | None, container: str | None, http_client=None, model: str | None = None
) -> AsyncIterator[bytes]:
    settings = get_settings()
    params = {"text": text, "model": model or settings.tts_model, "encoding": encoding}
    if sample_rate:
        params["sample_rate"] = sample_rate
    if container:
        params["container"] = container
    try:
        stream = _client(http_client).speak.v1.audio.generate(**params)
        if inspect.isawaitable(stream):
            stream = await stream
        async for chunk in stream:
            if chunk:
                yield chunk
    except TTSError:
        raise
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        detail = f"HTTP {status}: {getattr(exc, 'body', '')}" if status else type(exc).__name__
        raise TTSError(f"Text-to-speech failed ({detail})") from exc


async def synthesize(text: str, *, encoding: str = "mp3", http_client: httpx.AsyncClient | None = None) -> bytes:
    """One complete, playable audio buffer (MP3 by default)."""
    text = speakable(text)
    if not text:
        raise TTSError("Nothing to speak")
    audio = b"".join([chunk async for chunk in _chunks(text, encoding=encoding, sample_rate=None, container=None, http_client=http_client)])
    if not audio:
        raise TTSError("Text-to-speech returned no audio")
    return audio


async def stream_speech(
    text: str, *, sample_rate: int = 48000, http_client: httpx.AsyncClient | None = None, model: str | None = None
) -> AsyncIterator[bytes]:
    """Raw 16-bit mono PCM at `sample_rate`, chunk by chunk, for real-time playback."""
    text = speakable(text)
    if not text:
        return
    pending = b""
    async for chunk in _chunks(
        text, encoding="linear16", sample_rate=sample_rate, container="none", http_client=http_client, model=model
    ):
        pending += chunk
        whole = len(pending) - len(pending) % 2  # never split a 16-bit sample
        if whole:
            yield pending[:whole]
            pending = pending[whole:]


def pcm_to_wav(pcm: bytes, sample_rate: int = 48000) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV header (for saving or testing)."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()

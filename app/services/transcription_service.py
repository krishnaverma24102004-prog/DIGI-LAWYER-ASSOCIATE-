"""Real-time speech-to-text for raw audio frames on the live WebSocket, via Deepgram.

One `DeepgramTranscriber` per consultation holds a streaming connection to Deepgram.
Audio frames are forwarded as they arrive; Deepgram pushes results back
asynchronously, and they reach the session through callbacks:

* on_final(text, speaker)  - a finished piece of speech, ready for analysis
* on_interim(text)         - an in-progress guess, for live display only
* on_error(message)        - the connection failed; the session can start a new one
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass

from deepgram import AsyncDeepgramClient
from deepgram.listen.v1 import ListenV1Error, ListenV1Results

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Deepgram closes a stream after ~10s without audio; keep it open while the user is silent.
KEEPALIVE_INTERVAL_SECONDS = 4
CLOSE_TIMEOUT_SECONDS = 5
# Encodings for raw (headerless) audio. Containerized audio (webm, ogg, wav) needs no encoding.
RAW_ENCODINGS = {"linear16", "linear32", "flac", "alaw", "mulaw", "amr-nb", "amr-wb", "opus", "speex", "g729"}

OnFinal = Callable[[str, str | None], Awaitable[None]]
OnInterim = Callable[[str], Awaitable[None]]
OnError = Callable[[str], Awaitable[None]]


class TranscriptionNotConfigured(RuntimeError):
    pass


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioFormat:
    """What the client sends. Defaults match the browser test page: 16 kHz mono 16-bit PCM."""

    encoding: str | None = "linear16"
    sample_rate: int | None = 16000
    channels: int = 1

    @classmethod
    def from_client(cls, data: object) -> "AudioFormat":
        if not isinstance(data, dict):
            return cls()
        encoding = data.get("encoding", "linear16")
        if encoding is not None and encoding not in RAW_ENCODINGS:
            raise ValueError(f"Unsupported audio encoding {encoding!r}")
        sample_rate = data.get("sample_rate", 16000 if encoding else None)
        channels = data.get("channels", 1)
        if sample_rate is not None and (not isinstance(sample_rate, int) or not 8000 <= sample_rate <= 48000):
            raise ValueError("sample_rate must be an integer between 8000 and 48000")
        if not isinstance(channels, int) or not 1 <= channels <= 2:
            raise ValueError("channels must be 1 or 2")
        return cls(encoding=encoding, sample_rate=sample_rate if encoding else None, channels=channels)


def is_configured() -> bool:
    return bool(get_settings().deepgram_api_key)


def _describe(exc: Exception) -> str:
    """Short, client-safe error text. SDK exception strings include request headers."""
    status = getattr(exc, "status_code", None)
    if status:
        return f"HTTP {status}: {getattr(exc, 'body', '')}".strip()
    return type(exc).__name__


def _speaker_label(speaker: int | None) -> str | None:
    return None if speaker is None else f"Speaker {speaker + 1}"


def segments_from_result(result: ListenV1Results) -> list[tuple[str, str | None]]:
    """Split a final Deepgram result into (text, speaker) runs, one per speaker turn."""
    if not result.channel.alternatives:
        return []
    alternative = result.channel.alternatives[0]
    words = alternative.words or []
    if not words or all(w.speaker is None for w in words):
        text = alternative.transcript.strip()
        return [(text, None)] if text else []

    segments: list[tuple[str, str | None]] = []
    current_speaker = words[0].speaker
    current_words: list[str] = []
    for word in words:
        if word.speaker != current_speaker and current_words:
            segments.append((" ".join(current_words), _speaker_label(current_speaker)))
            current_words = []
        current_speaker = word.speaker
        current_words.append(word.punctuated_word or word.word)
    if current_words:
        segments.append((" ".join(current_words), _speaker_label(current_speaker)))
    return segments


class DeepgramTranscriber:
    def __init__(self, audio_format: AudioFormat, on_final: OnFinal, on_interim: OnInterim, on_error: OnError):
        self.audio_format = audio_format
        self._on_final = on_final
        self._on_interim = on_interim
        self._on_error = on_error
        self._stack = AsyncExitStack()
        self._socket = None
        self._listener: asyncio.Task | None = None
        self._keepalive: asyncio.Task | None = None
        self._last_audio_at = time.monotonic()
        self._closing = False
        self.failed = False

    async def start(self) -> None:
        settings = get_settings()
        options: dict = {
            "model": settings.deepgram_model,
            "language": settings.deepgram_language,
            "channels": self.audio_format.channels,
            "interim_results": "true",
            "punctuate": "true",
            "smart_format": "true",
            "endpointing": 300,
        }
        if self.audio_format.encoding:
            options["encoding"] = self.audio_format.encoding
            options["sample_rate"] = self.audio_format.sample_rate
        if settings.deepgram_diarize:
            options["diarize_model"] = "latest"

        client = AsyncDeepgramClient(api_key=settings.deepgram_api_key)
        try:
            self._socket = await self._stack.enter_async_context(client.listen.v1.connect(**options))
        except Exception as exc:
            await self._stack.aclose()
            logger.warning("Deepgram connect failed: %s", exc)
            raise TranscriptionError(f"Could not connect to Deepgram ({_describe(exc)})") from exc

        self._listener = asyncio.create_task(self._listen())
        self._keepalive = asyncio.create_task(self._keep_alive())

    async def feed(self, audio: bytes) -> None:
        if self.failed or self._closing or self._socket is None:
            raise TranscriptionError("Transcriber is not running")
        self._last_audio_at = time.monotonic()
        try:
            await self._socket.send_media(audio)
        except Exception as exc:
            self.failed = True
            logger.warning("Sending audio to Deepgram failed: %s", exc)
            raise TranscriptionError(f"Sending audio to Deepgram failed ({_describe(exc)})") from exc

    async def finalize(self) -> None:
        """Ask Deepgram to finish the current utterance now (e.g. when push-to-talk is released)."""
        if self._socket is not None and not (self.failed or self._closing):
            try:
                await self._socket.send_finalize()
            except Exception:
                logger.warning("Deepgram finalize failed", exc_info=True)

    async def close(self) -> None:
        """Flush buffered audio, wait for the last results, then disconnect."""
        if self._closing:
            return
        self._closing = True
        if self._keepalive:
            self._keepalive.cancel()
        try:
            if self._socket is not None and not self.failed:
                # Deepgram sends any remaining results, then closes its side.
                await self._socket.send_close_stream()
                if self._listener:
                    await asyncio.wait_for(asyncio.shield(self._listener), timeout=CLOSE_TIMEOUT_SECONDS)
        except Exception:
            logger.warning("Deepgram did not close cleanly", exc_info=True)
        finally:
            if self._listener and not self._listener.done():
                self._listener.cancel()
            await self._stack.aclose()

    async def _listen(self) -> None:
        try:
            async for message in self._socket:
                if isinstance(message, ListenV1Results):
                    await self._handle_result(message)
                elif isinstance(message, ListenV1Error):
                    logger.warning("Deepgram error: %s", message.description)
                    await self._on_error(f"Deepgram error: {message.description}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closing:
                self.failed = True
                logger.warning("Deepgram stream failed: %s", exc)
                await self._on_error(f"Transcription stream lost ({_describe(exc)})")

    async def _handle_result(self, result: ListenV1Results) -> None:
        if result.is_final:
            for text, speaker in segments_from_result(result):
                await self._on_final(text, speaker)
        elif result.channel.alternatives:
            text = result.channel.alternatives[0].transcript.strip()
            if text:
                await self._on_interim(text)

    async def _keep_alive(self) -> None:
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
            if time.monotonic() - self._last_audio_at >= KEEPALIVE_INTERVAL_SECONDS:
                try:
                    await self._socket.send_keep_alive()
                except Exception:
                    return


async def create_transcriber(
    audio_format: AudioFormat, on_final: OnFinal, on_interim: OnInterim, on_error: OnError
) -> DeepgramTranscriber:
    if not is_configured():
        raise TranscriptionNotConfigured(
            "Server-side audio transcription is not configured (DEEPGRAM_API_KEY is not set). "
            "Send transcript_chunk messages instead."
        )
    transcriber = DeepgramTranscriber(audio_format, on_final, on_interim, on_error)
    await transcriber.start()
    return transcriber

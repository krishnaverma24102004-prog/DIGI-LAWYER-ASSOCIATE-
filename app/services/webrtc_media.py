"""WebRTC media plumbing for talking mode (aiortc).

  DataChannelTransport  makes an RTCDataChannel look like the Starlette WebSocket the live
                        session expects (receive / send_json / close), so the same session
                        code and JSON protocol run over WebRTC.
  SpeechTrack           the outbound audio track: plays queued 48 kHz PCM from text-to-speech
                        in real-time 20 ms frames, and silence when there is nothing to say.
  WebRTCAudioOutput     talking-mode output that streams TTS audio into a SpeechTrack as
                        Deepgram produces it, so playback starts before synthesis finishes.
  pcm_frames            converts inbound microphone frames (Opus decoded by aiortc, usually
                        48 kHz stereo) to 16 kHz mono PCM batches for speech-to-text.
"""

import asyncio
import fractions
import json
import logging
import time

import numpy as np
from aiortc import MediaStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame, AudioResampler

from app.services import tts_service

logger = logging.getLogger(__name__)

OUT_RATE = 48000
FRAME_SAMPLES = 960  # 20 ms at 48 kHz
FRAME_BYTES = FRAME_SAMPLES * 2
STT_RATE = 16000
STT_BATCH_BYTES = STT_RATE * 2 // 10  # send ~100 ms of audio per batch
MAX_PENDING_MESSAGES = 200


class DataChannelTransport:
    """The live session's transport over an RTCDataChannel."""

    def __init__(self):
        self._incoming: asyncio.Queue[dict] = asyncio.Queue()
        self._channel = None
        self._pending: list[str] = []
        self.closed = False

    def bind(self, channel) -> None:
        self._channel = channel

        @channel.on("message")
        def on_message(message):
            if isinstance(message, str):
                self._incoming.put_nowait({"type": "websocket.receive", "text": message})

        @channel.on("open")
        def on_open():
            self._flush()

        @channel.on("close")
        def on_close():
            self.disconnect()

        if channel.readyState == "open":
            self._flush()

    def _flush(self) -> None:
        while self._pending and self._channel is not None and self._channel.readyState == "open":
            self._channel.send(self._pending.pop(0))

    async def receive(self) -> dict:
        return await self._incoming.get()

    async def send_json(self, payload: dict) -> None:
        text = json.dumps(payload)
        if self._channel is not None and self._channel.readyState == "open":
            self._flush()
            self._channel.send(text)
        elif not self.closed and len(self._pending) < MAX_PENDING_MESSAGES:
            self._pending.append(text)  # before the channel opens

    async def close(self, code: int = 1000) -> None:
        if self._channel is not None and self._channel.readyState == "open":
            self._channel.close()
        self.disconnect()

    def disconnect(self) -> None:
        if not self.closed:
            self.closed = True
            self._incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})


class SpeechTrack(MediaStreamTrack):
    """Outbound audio: queued speech, otherwise silence, paced in real time."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self._buffer = bytearray()
        self._timestamp = 0
        self._start: float | None = None
        self._drained = asyncio.Event()
        self._drained.set()

    def enqueue(self, pcm: bytes) -> None:
        self._buffer.extend(pcm)
        self._drained.clear()

    def clear(self) -> None:
        self._buffer.clear()
        self._drained.set()

    @property
    def buffered_seconds(self) -> float:
        return len(self._buffer) / 2 / OUT_RATE

    async def wait_until_played(self) -> None:
        await self._drained.wait()

    async def recv(self) -> AudioFrame:
        if self.readyState != "live":
            raise MediaStreamError
        if self._start is None:
            self._start = time.time()
        else:
            self._timestamp += FRAME_SAMPLES
            delay = self._start + self._timestamp / OUT_RATE - time.time()
            if delay > 0:
                await asyncio.sleep(delay)

        if len(self._buffer) >= FRAME_BYTES:
            chunk = bytes(self._buffer[:FRAME_BYTES])
            del self._buffer[:FRAME_BYTES]
        else:
            chunk = bytes(self._buffer).ljust(FRAME_BYTES, b"\x00")
            self._buffer.clear()
        if not self._buffer:
            self._drained.set()

        frame = AudioFrame.from_ndarray(np.frombuffer(chunk, dtype=np.int16).reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = OUT_RATE
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(1, OUT_RATE)
        return frame


class WebRTCAudioOutput:
    """Talking mode over WebRTC: TTS audio streams into the outbound track as it arrives."""

    def __init__(self, track: SpeechTrack):
        self.track = track

    async def speak(self, text: str) -> None:
        async for pcm in tts_service.stream_speech(text, sample_rate=OUT_RATE):
            self.track.enqueue(pcm)
        try:
            # Returns when the listener has heard it (bounded, in case the peer stopped reading).
            await asyncio.wait_for(self.track.wait_until_played(), timeout=self.track.buffered_seconds + 5)
        except TimeoutError:
            self.track.clear()

    def interrupt(self) -> None:
        self.track.clear()


async def pcm_frames(track: MediaStreamTrack):
    """Yield ~100 ms batches of 16 kHz mono 16-bit PCM from an inbound audio track."""
    resampler = AudioResampler(format="s16", layout="mono", rate=STT_RATE)
    batch = bytearray()
    while True:
        try:
            frame = await track.recv()
        except MediaStreamError:
            break
        for resampled in resampler.resample(frame):
            batch.extend(resampled.to_ndarray().tobytes())
        if len(batch) >= STT_BATCH_BYTES:
            yield bytes(batch)
            batch.clear()
    if batch:
        yield bytes(batch)

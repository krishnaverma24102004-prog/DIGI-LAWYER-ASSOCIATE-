"""A phone call as a live consultation: Twilio Media Stream <-> the live session pipeline.

  TwilioTransport      makes the Twilio Media Stream socket look like the WebSocket the live
                       session expects: inbound mu-law "media" frames become 8 kHz PCM audio
                       frames, "stop" ends the session. JSON the session would show in the app
                       has no screen on a phone call and is dropped.
  TwilioAudioOutput    talking-mode output: Deepgram Aura speech at 8 kHz -> mu-law -> 20 ms
                       "media" frames back to the caller; "clear" stops playback on barge-in.
  TelephonySession     the live session in conversation mode with a voice, run for the
                       organization that owns the dialled number.

A call has no signed-in user, so database access uses the service role, scoped explicitly
to the number's organization (the number was verified via Twilio's webhook signature and
the stream token). The transcript is saved as the number's owner, the lawyer receiving
the intake. Speech is PII-masked before the agents see it, as in every live session.
"""

import asyncio
import base64
import binascii
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.core import metrics
from app.core.config import get_settings
from app.database import get_supabase_admin
from app.dependencies.auth import CurrentUser
from app.services import intake_guard, transcription_service, tts_service, twilio_service
from app.services.live_session import LiveConsultationSession
from app.services.prompt_engine import PracticeAreaProfile

logger = logging.getLogger(__name__)

PHONE_ROLE = "telephony"


class TwilioTransport:
    """receive / send_json / close over a Twilio Media Stream WebSocket."""

    def __init__(self, websocket: WebSocket, stream_sid: str):
        self.ws = websocket
        self.stream_sid = stream_sid
        self._send_lock = asyncio.Lock()
        self.on_mark = None  # callback(name) when Twilio has played up to a mark
        self.closed = False

    async def receive(self) -> dict:
        while True:
            try:
                raw = await self.ws.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                self.closed = True
                return {"type": "websocket.disconnect"}
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            match event.get("event"):
                case "media":
                    media = event.get("media") or {}
                    if media.get("track", "inbound") != "inbound":
                        continue
                    try:
                        mulaw = base64.b64decode(media.get("payload", ""))
                    except binascii.Error:
                        continue
                    return {"type": "websocket.receive", "bytes": twilio_service.mulaw_to_pcm16(mulaw)}
                case "stop":
                    return {"type": "websocket.disconnect"}
                case "mark":
                    if self.on_mark:
                        self.on_mark((event.get("mark") or {}).get("name"))
                case _:
                    continue  # connected, dtmf, ...

    async def send_json(self, payload: dict) -> None:
        if payload.get("type") == "error":
            logger.info("Phone session %s: %s", self.stream_sid, payload.get("message"))

    async def send_text(self, message: str) -> None:
        if self.closed:
            return
        async with self._send_lock:
            try:
                await self.ws.send_text(message)
            except Exception:
                self.closed = True

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                await self.ws.close()
            except Exception:
                pass


class TwilioAudioOutput:
    """Speaks replies to the caller as 8 kHz mu-law, streamed while Aura synthesizes."""

    def __init__(self, transport: TwilioTransport):
        self.transport = transport
        self.replies = 0
        self.pending_latency_from: float | None = None  # when the caller's last sentence ended

    async def speak(self, text: str) -> None:
        self.replies += 1
        voice = get_settings().telephony_voice or None
        leftover = b""
        async for pcm in tts_service.stream_speech(text, sample_rate=twilio_service.SAMPLE_RATE, model=voice):
            mulaw = leftover + twilio_service.pcm16_to_mulaw(pcm)
            whole = len(mulaw) - len(mulaw) % twilio_service.FRAME_BYTES
            leftover = mulaw[whole:]
            for frame in twilio_service.frames(mulaw[:whole]):
                self._observe_latency()
                await self.transport.send_text(twilio_service.media_message(self.transport.stream_sid, frame))
        if leftover:
            await self.transport.send_text(twilio_service.media_message(self.transport.stream_sid, leftover))
        await self.transport.send_text(twilio_service.mark_message(self.transport.stream_sid, f"reply-{self.replies}"))

    def _observe_latency(self) -> None:
        if self.pending_latency_from is not None:
            metrics.TELEPHONY_RESPONSE_LATENCY.observe(time.monotonic() - self.pending_latency_from)
            self.pending_latency_from = None

    def interrupt(self) -> None:
        # Drop what Twilio has buffered; the caller is speaking.
        asyncio.ensure_future(self.transport.send_text(twilio_service.clear_message(self.transport.stream_sid)))


PHONE_NOTICE = "This call is answered by an AI assistant and recorded for the firm's lawyers."


class TelephonySession(LiveConsultationSession):
    def __init__(self, transport: TwilioTransport, number: dict, *, call_sid: str, caller: str | None):
        self.number = number
        self.call_sid = call_sid
        self.phone_output = TwilioAudioOutput(transport)
        super().__init__(
            transport,
            CurrentUser(id=number["owner_user_id"], email=None, access_token=""),
            number["org_id"],
            PHONE_ROLE,
            practice_area_id=number.get("practice_area_id"),
            mode="conversation",
            voice=True,
            jurisdiction=number.get("jurisdiction"),
            audio_output=self.phone_output,
            transport="telephony",
            consent="phone",
        )
        if self.audio_output is None:
            logger.warning("Phone session %s has no voice: text-to-speech is not configured", call_sid)
        self.audio_format = transcription_service.AudioFormat("linear16", twilio_service.SAMPLE_RATE, 1)
        self.client_metadata = {"channel": "phone", "call_sid": call_sid, "caller": caller,
                                "dialled": number.get("phone_number")}
        self.title = f"Phone intake {caller or 'unknown caller'}"
        self._greeted = False
        # Intake only: the AI asks questions; replies with legal substance are kept for the lawyer
        # (in the transcript metadata) and the caller hears that a lawyer will get back to them.
        self.intake_only = True
        self.held_replies: list[dict] = []
        self.client_metadata["held_replies"] = self.held_replies

    def _db(self):
        """No user on a phone call: service role, every query scoped to this org by the caller."""
        return get_supabase_admin()

    async def _load_practice_area(self) -> None:
        def load():
            rows = (
                get_supabase_admin().table("practice_areas")
                .select("id, name, custom_system_prompt, risk_evaluation_rules")
                .eq("id", self.practice_area_id).eq("org_id", self.org_id).limit(1).execute().data
            )
            return PracticeAreaProfile.from_row(rows[0]) if rows else None

        try:
            self.practice_area = await run_in_threadpool(load)
        except Exception:
            logger.exception("Loading practice area %s failed for call %s", self.practice_area_id, self.call_sid)
            self.practice_area = None
        if self.practice_area is None:
            self.practice_area_id = None

    async def _save_transcript(self, row: dict) -> dict:
        row = {**row, "user_id": self.user.id, "source": "phone"}
        return await run_in_threadpool(
            lambda: get_supabase_admin().table("transcripts").insert(row).execute().data[0]
        )

    async def _on_transcript_final(self, text: str, speaker: str | None) -> None:
        self.phone_output.pending_latency_from = time.monotonic()
        await super()._on_transcript_final(text, "Caller")

    def _public_reply(self, masked_message: str) -> str:
        safe, reasons = intake_guard.check_reply(masked_message)
        if safe:
            return masked_message
        self.held_replies.append({"at": datetime.now(timezone.utc).isoformat(), "reasons": reasons,
                                  "draft": self.masker.unmask(masked_message)})
        return intake_guard.HOLDING_LINE

    async def _on_transcript_interim(self, text: str) -> None:
        # Barge-in: the caller talking over the AI stops its reply.
        if self._speech_task is not None and not self._speech_task.done():
            self._interrupt_speech()

    async def _run(self) -> None:
        greeting = self.number.get("greeting") or get_settings().telephony_default_greeting
        if "record" not in greeting.lower():
            greeting = f"{greeting} {PHONE_NOTICE}"
        if greeting and self.audio_output is not None and not self._greeted:
            self._greeted = True
            self._add_assistant_turn(greeting, greeting)
            self._start_speech(greeting)
        await super()._run()

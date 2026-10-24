"""One live consultation over a WebSocket: collect transcript, run the agents, finalize.

Every finalized piece of speech is PII-masked as it arrives (core/guardrails.py); only
the masked text ever reaches the agents or Claude, while the original is kept for the
firm's own record. Analysis passes run the LangGraph agent team
(services/agent_workflow.py) in a background task, so receiving speech never waits on
the models. Speech that arrives during a pass is coalesced into the next pass.

Context available to the agents: the practice area chosen at connect time, an attached
contract, knowledge-base passages (searched by the researcher agent, rate-limited by
RAG_REFRESH_SECONDS / RAG_MIN_NEW_CHARS), and, when the session belongs to a case
thread, summaries of the case's earlier sessions. Each agent's progress is streamed to
the client as `agent_status`, so the UI can show what the AI is doing.

Modes:
  copilot       (default) the drafter writes notes for the lawyer running the consultation
  conversation  the drafter replies to the user, the replies become turns in the transcript,
                and with an audio output attached (talking mode) each reply is spoken back

The session is transport-agnostic: anything with receive()/send_json()/close() in the
Starlette WebSocket shape works, which is how the WebRTC data channel reuses it
(routers/webrtc.py), with audio going to an AudioOutput instead of the socket.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from typing import Protocol

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.core import metrics
from app.core.config import get_settings
from app.core.guardrails import PiiMasker, mask_pii
from app.dependencies.auth import CurrentUser, verify_access_token
from app.models.analysis import LiveAnalysis
from app.database import get_supabase_for_user
from app.services import (
    agent_workflow,
    anthropic_service,
    audit_service,
    citation_service,
    document_service,
    memory_service,
    n8n_service,
    prompt_engine,
    queue_service,
    jurisdiction_service,
    rag_service,
    stripe_service,
    transcript_service,
    transcription_service,
    tts_service,
    web_search,
)
from app.services.audit_service import AuditAction
from app.services.agent_workflow import AgentContext
from app.services.document_service import DocumentContext
from app.services.memory_service import CaseMemory
from app.services.prompt_engine import PracticeAreaProfile
from app.services.rag_service import Precedent
from app.services.web_search import WebResult

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 10_000
MAX_TRANSCRIPT_CHARS = 500_000
FINAL_ANALYSIS_WAIT_SECONDS = 20
MAX_RAG_FAILURES = 3
MAX_SUMMARY_PRECEDENTS = 8
MAX_WEB_FAILURES = 3
ASSISTANT_SPEAKER = "AI Assistant"
# Push-to-talk: audio still arriving this long after release is the tail of the utterance.
PTT_TAIL_SECONDS = 0.5
# Audio frames further apart than this start a new stretch of speech (for metering).
AUDIO_GAP_SECONDS = 1.5
CONSENT_METHODS = ("verbal", "written", "whatsapp", "phone")
CONSENT_VALID_DAYS = 365
CONSENT_REQUIRED_MESSAGE = (
    "The client's consent to AI processing isn't recorded. AI analysis and speech-to-text are off; "
    "typed notes are saved. Record consent to turn them on."
)


class AudioOutput(Protocol):
    """Where talking mode sends speech: the WebSocket (MP3 buffers) or a WebRTC track (PCM)."""

    async def speak(self, text: str) -> None: ...

    def interrupt(self) -> None: ...


class WebSocketAudioOutput:
    """Sends each reply as one playable MP3 buffer over the session's socket."""

    def __init__(self, session: "LiveConsultationSession"):
        self.session = session

    async def speak(self, text: str) -> None:
        import base64

        audio = await tts_service.synthesize(text, encoding="mp3")
        await self.session._send(
            {"type": "agent_audio", "encoding": "mp3", "audio": base64.b64encode(audio).decode(), "text": tts_service.speakable(text)}
        )

    def interrupt(self) -> None:
        pass  # the browser stops its own playback; the next reply replaces this one


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class TranscriptSegment:
    text: str  # as spoken; stored in the firm's database only
    speaker: str | None
    source: str  # "client_text" or "audio"
    received_at: str
    masked_text: str = ""  # PII-masked; the only version sent to LLMs

    def render(self, masked: bool = True) -> str:
        text = self.masked_text if masked else self.text
        return f"{self.speaker}: {text}" if self.speaker else text


class LiveConsultationSession:
    def __init__(
        self,
        websocket: WebSocket,
        user: CurrentUser,
        org_id: str,
        role: str,
        *,
        practice_area_id: str | None = None,
        thread_id: str | None = None,
        document_context: DocumentContext | None = None,
        ip_address: str | None = None,
        mode: str = "copilot",
        voice: bool = False,
        jurisdiction: str | None = None,
        audio_output: AudioOutput | None = None,
        transport: str = "websocket",
        consent: str | None = None,
    ):
        self.ws = websocket
        # The client's consent to AI processing: given now ("verbal", "written", ...), or found on
        # the case thread (valid for CONSENT_VALID_DAYS). Without it the session keeps typed notes only.
        self.consent_method = consent if consent in CONSENT_METHODS else None
        self.consent: dict | None = None if get_settings().consultation_consent_required else {"required": False}
        self._consent_warned = False
        # websocket, webrtc or telephony: how audio usage is metered.
        self.transport = transport
        self.audio_received = False
        # Seconds of audio actually streamed to speech-to-text: what the session is billed for.
        self.audio_seconds = 0.0
        self._audio_last_at: float | None = None
        # Push-to-talk state (WebRTC): microphone audio is only transcribed while the button is held.
        self.talking = False
        self._ptt_released_at = float("-inf")
        self._ptt_finalize_task: asyncio.Task | None = None
        self.mode = mode if mode in ("copilot", "conversation") else "copilot"
        # Statutory framework, citation style and knowledge-base filter for this consultation.
        self.jurisdiction = jurisdiction_service.get_profile(jurisdiction)
        # Talking mode: speak replies through `audio_output` (WebSocket MP3 by default).
        self.audio_output: AudioOutput | None = None
        if voice and tts_service.is_configured():
            self.audio_output = audio_output or WebSocketAudioOutput(self)
        self._speech_task: asyncio.Task | None = None
        self.user = user
        self.org_id = org_id
        self.role = role
        self.ip_address = ip_address
        self.practice_area_id = practice_area_id
        self.practice_area: PracticeAreaProfile | None = None
        self.session_id = str(uuid4())
        self.started_at = _now()
        self.title: str | None = None
        self.client_metadata: dict = {}
        self.intake_only = False  # public channels: the agents only ask intake questions
        self.segments: list[TranscriptSegment] = []
        self.transcript_chars = 0
        self.analysis = LiveAnalysis()
        self.analysis_enabled = anthropic_service.is_configured()
        # A contract attached to the consultation (masked); the agents cross-reference it.
        self.document_context = document_context
        # Case thread whose earlier sessions the agents remember.
        self.thread_id = thread_id
        self.case_memory: CaseMemory | None = None
        # One masker per session keeps placeholders consistent ([BANK_ACCT] stays the same account).
        self.masker = PiiMasker()
        self.pii_redactions = 0
        self.disclaimers_applied = 0
        # What the agents carry from one pass to the next.
        self.agent_state: agent_workflow.State = {}
        self.agent_message: str | None = None
        self._agent_cursor = 0  # segments already given to the agents

        self._connected = True
        self._send_lock = asyncio.Lock()
        self._analysis_task: asyncio.Task | None = None
        self._analysis_pending = False
        self.audio_format = transcription_service.AudioFormat()
        self._transcriber: transcription_service.DeepgramTranscriber | None = None
        self._transcriber_lock = asyncio.Lock()
        self._audio_unavailable = False

        settings = get_settings()
        self.rag_enabled = settings.rag_enabled
        # Passages currently in Claude's context, and every passage matched this session.
        self.precedents: list[Precedent] = []
        self.matched_precedents: dict[str, Precedent] = {}
        self._rag_last_at = 0.0
        self._rag_last_chars = 0
        self._rag_failures = 0
        # Live web search (external researcher): rate-limited per session.
        self.web_sources: dict[str, WebResult] = {}
        self._web_last_at = 0.0
        self._web_searches = 0
        self._web_failures = 0

    def _db(self):
        """Supabase client acting as the user in this session's organization."""
        return get_supabase_for_user(self.user.access_token, self.org_id)

    # ------------------------------------------------------------------ main loop

    async def run(self) -> None:
        gauge = metrics.LIVE_SESSIONS_ACTIVE.labels(transport=self.transport)
        gauge.inc()
        try:
            await self._run()
        finally:
            gauge.dec()

    async def _run(self) -> None:
        await self._send(
            {
                "type": "session_started",
                "session_id": self.session_id,
                "user_id": self.user.id,
                "org_id": self.org_id,
                "role": self.role,
                "mode": self.mode,
                "voice": self.audio_output is not None,
                "jurisdiction": self.jurisdiction.code if self.jurisdiction else None,
            }
        )
        if self.practice_area_id:
            await self._load_practice_area()
        if self.thread_id:
            await self._load_case_memory()
        await self._resolve_consent()
        try:
            await audit_service.alog_action(
                self.user.id,
                self.org_id,
                AuditAction.START_CONSULTATION,
                "consultation",
                self.session_id,
                ip_address=self.ip_address,
                metadata={
                    "practice_area": self.practice_area.name if self.practice_area else None,
                    "thread_id": self.thread_id,
                },
            )
        except audit_service.AuditError as exc:
            # Fail-closed auditing: no consultation without its audit entry.
            await self._send_error("audit_unavailable", str(exc))
            await self.ws.close()
            return
        if not self.analysis_enabled and self.consent is not None:
            await self._send_error(
                "analysis_unavailable",
                "Live analysis is off: ANTHROPIC_API_KEY is not configured. Transcript is still recorded.",
            )

        end_reason = "disconnected"
        try:
            while True:
                message = await self.ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await self._handle_audio(message["bytes"])
                    continue
                if message.get("text") is None:
                    continue

                try:
                    event = json.loads(message["text"])
                except json.JSONDecodeError:
                    await self._send_error("invalid_json", "Messages must be JSON objects")
                    continue
                if not isinstance(event, dict):
                    await self._send_error("invalid_message", "Messages must be JSON objects")
                    continue

                if event.get("type") == "end":
                    end_reason = "client_end"
                    break
                await self._dispatch(event)
        except WebSocketDisconnect:
            pass

        if end_reason == "disconnected":
            self._connected = False
        # Runs on disconnect too, so a dropped connection doesn't lose the consultation.
        await self.finalize(end_reason)
        if self._connected:
            await self.ws.close()

    async def _dispatch(self, event: dict) -> None:
        match event.get("type"):
            case "transcript_chunk":
                await self._handle_transcript_chunk(event)
            case "start":
                await self._handle_start(event)
            case "auth":
                await self._handle_auth_refresh(event)
            case "ping":
                await self._send({"type": "pong"})
            case "interrupt":
                self._interrupt_speech()
            case "ptt":
                await self._handle_push_to_talk(event)
            case "consent":
                await self._record_consent(event.get("method"))
            case other:
                await self._send_error("unknown_type", f"Unknown message type: {other!r}")

    # ------------------------------------------------------------------ inbound events

    async def _handle_start(self, event: dict) -> None:
        if isinstance(event.get("title"), str):
            self.title = event["title"].strip()[:200] or None
        if isinstance(event.get("metadata"), dict):
            self.client_metadata = event["metadata"]
        if event.get("document_id"):
            await self._attach_document(event["document_id"])
        if "audio" in event:
            if self._transcriber is not None:
                await self._send_error("invalid_audio_format", "Audio format must be set before streaming audio")
                return
            try:
                self.audio_format = transcription_service.AudioFormat.from_client(event["audio"])
            except ValueError as exc:
                await self._send_error("invalid_audio_format", str(exc))

    # ------------------------------------------------------------------ consent

    async def _resolve_consent(self) -> None:
        if not get_settings().consultation_consent_required:
            self.consent = {"required": False}
            return
        if self.consent_method:
            await self._record_consent(self.consent_method)
            return
        if self.thread_id:
            try:
                thread = await run_in_threadpool(memory_service.get_thread, self._db(), self.thread_id)
            except Exception:
                logger.exception("Reading consent of thread %s failed in session %s", self.thread_id, self.session_id)
                thread = None
            given = _parse_time((thread or {}).get("ai_consent_at"))
            if given and _now() - given < timedelta(days=CONSENT_VALID_DAYS):
                self.consent = {"method": thread.get("ai_consent_method"), "at": given.isoformat(),
                                "by": thread.get("ai_consent_by"), "source": "case_thread"}
                await self._send({"type": "consent_status", "consent": self.consent})
                return
        self.analysis_enabled = False
        await self._send({"type": "consent_required", "message": CONSENT_REQUIRED_MESSAGE, "methods": list(CONSENT_METHODS)})

    async def _record_consent(self, method: object) -> None:
        """The lawyer confirms the client agreed to AI processing; it is remembered on the case thread."""
        if method not in CONSENT_METHODS:
            await self._send_error("invalid_consent", f"Consent method must be one of {', '.join(CONSENT_METHODS)}")
            return
        at = _now()
        if self.thread_id:
            try:
                await run_in_threadpool(
                    lambda: self._db().table("case_threads").update({"ai_consent_at": at.isoformat(), "ai_consent_method": method})
                    .eq("id", self.thread_id).execute()
                )
            except Exception:
                logger.exception("Recording consent on thread %s failed in session %s", self.thread_id, self.session_id)
        self.consent = {"method": method, "at": at.isoformat(), "by": self.user.id, "source": "this_session"}
        self.analysis_enabled = anthropic_service.is_configured()
        try:
            await audit_service.alog_action(self.user.id, self.org_id, AuditAction.RECORD_CONSENT, "consultation",
                                            self.session_id, ip_address=self.ip_address,
                                            metadata={"method": method, "thread_id": self.thread_id})
        except audit_service.AuditError as exc:
            await self._send_error("audit_unavailable", str(exc))
        await self._send({"type": "consent_recorded", "consent": self.consent})
        if self.segments:
            self._schedule_analysis()

    async def _load_practice_area(self) -> None:
        try:
            self.practice_area = await run_in_threadpool(
                prompt_engine.load_practice_area, self.user.access_token, self.org_id, self.practice_area_id
            )
        except Exception:
            logger.exception("Loading practice area %s failed in session %s", self.practice_area_id, self.session_id)
            self.practice_area = None
        if self.practice_area is None:
            self.practice_area_id = None
            await self._send_error("practice_area_not_found", "Practice area not found; using general analysis")
            return
        await self._send(
            {"type": "practice_area_selected", "practice_area_id": self.practice_area.id, "name": self.practice_area.name}
        )

    async def _load_case_memory(self) -> None:
        try:
            self.case_memory = await run_in_threadpool(memory_service.load_case_memory, self._db(), self.thread_id)
        except Exception:
            logger.exception("Loading case thread %s failed in session %s", self.thread_id, self.session_id)
            self.case_memory = None
        if self.case_memory is None:
            self.thread_id = None
            await self._send_error("thread_not_found", "Case thread not found; this session won't be linked to it")
            return
        await self._send(
            {
                "type": "case_memory_loaded",
                "thread_id": self.thread_id,
                "title": self.case_memory.title,
                "previous_sessions": self.case_memory.session_count,
            }
        )

    async def _attach_document(self, document_id: object) -> None:
        try:
            document_id = str(UUID(str(document_id)))
        except ValueError:
            await self._send_error("document_not_found", "document_id is not a valid id")
            return
        try:
            # User-scoped read in this org: RLS decides whether this user may use the document.
            row = await run_in_threadpool(
                document_service.get_document, self.user.access_token, document_id, include_text=True, org_id=self.org_id
            )
        except Exception:
            logger.exception("Loading document %s failed in session %s", document_id, self.session_id)
            await self._send_error("document_load_failed", "Could not load the document")
            return
        if row is None:
            await self._send_error("document_not_found", "Document not found")
            return

        original = DocumentContext.from_row(row)
        try:
            masked = await run_in_threadpool(mask_pii, original.text, self.masker)
        except Exception:
            logger.exception("PII masking of document %s failed", document_id)
            await self._send_error("pii_masking_failed", "The document could not be checked for personal data; not attached")
            return
        self.pii_redactions += len(masked.entities)
        self.document_context = DocumentContext(original.document_id, original.filename, masked.text)
        await self._send(
            {
                "type": "document_attached",
                "document_id": document_id,
                "filename": self.document_context.filename,
                "char_count": len(self.document_context.text),
                "pii_redactions": len(masked.entities),
                # False for very long documents: analysis then sees the most relevant clauses.
                "complete_in_context": self.document_context.is_complete,
            }
        )
        if self.segments:
            self._schedule_analysis()

    async def _handle_transcript_chunk(self, event: dict) -> None:
        text = str(event.get("text") or "").strip()
        if not text:
            await self._send_error("empty_chunk", "transcript_chunk.text is empty")
            return
        if len(text) > MAX_CHUNK_CHARS:
            await self._send_error("chunk_too_large", f"Chunks are limited to {MAX_CHUNK_CHARS} characters")
            return
        speaker = str(event.get("speaker") or "").strip()[:50] or None
        await self._add_segment(text, speaker, source="client_text")

    async def _handle_push_to_talk(self, event: dict) -> None:
        """Hold-to-talk: pressing stops the AI talking; releasing finishes the utterance."""
        if event.get("state") == "start":
            self.talking = True
            if self._ptt_finalize_task is not None:
                self._ptt_finalize_task.cancel()
            self._interrupt_speech()
        elif event.get("state") == "stop":
            self.talking = False
            self._ptt_released_at = time.monotonic()
            self._ptt_finalize_task = asyncio.create_task(self._finalize_after_release())

    async def _finalize_after_release(self) -> None:
        # Let the last frames (still in flight when the button was released) reach Deepgram first.
        await asyncio.sleep(PTT_TAIL_SECONDS)
        if not self.talking and self._transcriber is not None:
            await self._transcriber.finalize()

    def accepts_push_to_talk_audio(self) -> bool:
        """Whether microphone audio should be transcribed now: while held, plus a short tail."""
        return self.talking or time.monotonic() - self._ptt_released_at < PTT_TAIL_SECONDS

    async def handle_pcm_audio(self, pcm: bytes, sample_rate: int = 16000) -> None:
        """Entry point for transports that deliver decoded audio (WebRTC) instead of socket frames."""
        if self._transcriber is None and self.audio_format.sample_rate != sample_rate:
            self.audio_format = transcription_service.AudioFormat("linear16", sample_rate, 1)
        await self._handle_audio(pcm)

    async def _handle_audio(self, audio: bytes) -> None:
        """Forward a raw audio frame to Deepgram; final text comes back via _on_transcript_final."""
        if self._audio_unavailable:
            return
        if self.consent is None:
            # No consent, no speech-to-text: the client's voice isn't sent anywhere.
            if not self._consent_warned:
                self._consent_warned = True
                await self._send_error("consent_required", CONSENT_REQUIRED_MESSAGE)
            return
        self.audio_received = True
        self._count_audio_time()
        try:
            transcriber = await self._ensure_transcriber()
            await transcriber.feed(audio)
        except transcription_service.TranscriptionNotConfigured as exc:
            self._audio_unavailable = True
            await self._send_error("audio_transcription_unavailable", str(exc))
        except transcription_service.TranscriptionError as exc:
            # Drop the broken stream; the next frame opens a new one.
            logger.warning("Transcription failed in session %s: %s", self.session_id, exc)
            await self._discard_transcriber()
            await self._send_error("transcription_failed", str(exc))

    def _count_audio_time(self) -> None:
        """Add the time since the previous frame, unless there was a pause (a new stretch of speech)."""
        now = time.monotonic()
        if self._audio_last_at is not None and now - self._audio_last_at <= AUDIO_GAP_SECONDS:
            self.audio_seconds += now - self._audio_last_at
        self._audio_last_at = now

    async def _ensure_transcriber(self) -> transcription_service.DeepgramTranscriber:
        async with self._transcriber_lock:
            if self._transcriber is not None and self._transcriber.failed:
                await self._discard_transcriber()
            if self._transcriber is None:
                self._transcriber = await transcription_service.create_transcriber(
                    self.audio_format,
                    on_final=self._on_transcript_final,
                    on_interim=self._on_transcript_interim,
                    on_error=self._on_transcription_error,
                )
            return self._transcriber

    async def _discard_transcriber(self) -> None:
        transcriber, self._transcriber = self._transcriber, None
        if transcriber is not None:
            await transcriber.close()

    async def _on_transcript_final(self, text: str, speaker: str | None) -> None:
        await self._add_segment(text, speaker, source="audio")

    async def _on_transcript_interim(self, text: str) -> None:
        await self._send({"type": "transcript_interim", "text": text})

    async def _on_transcription_error(self, message: str) -> None:
        await self._send_error("transcription_failed", message)

    async def _handle_auth_refresh(self, event: dict) -> None:
        """Let clients swap in a refreshed JWT during a long consultation."""
        token = event.get("token")
        if not isinstance(token, str) or not token:
            await self._send_error("invalid_token", "auth.token is required")
            return
        try:
            user = await run_in_threadpool(verify_access_token, token)
        except Exception:
            await self._send_error("invalid_token", "Token is invalid or expired")
            return
        if user.id != self.user.id:
            await self._send_error("invalid_token", "Token belongs to a different user")
            return
        self.user = user
        await self._send({"type": "auth_refreshed"})

    async def _add_segment(self, text: str, speaker: str | None, source: str) -> None:
        if self.transcript_chars + len(text) > MAX_TRANSCRIPT_CHARS:
            await self._send_error("transcript_limit", "Session transcript limit reached; end the session")
            return
        try:
            masked = await run_in_threadpool(mask_pii, text, self.masker)
        except Exception:
            # Fail closed: without masking, nothing more goes to the LLMs this session.
            logger.exception("PII masking failed in session %s", self.session_id)
            if self.analysis_enabled:
                self.analysis_enabled = False
                await self._send_error("pii_masking_failed", "Personal-data masking failed; AI analysis stopped for this session")
            masked = None

        self.segments.append(
            TranscriptSegment(text, speaker, source, _now().isoformat(), masked.text if masked else "[unmasked text withheld]")
        )
        self.transcript_chars += len(text)
        redactions = [e["placeholder"] for e in masked.entities] if masked else []
        self.pii_redactions += len(redactions)
        await self._send(
            {
                "type": "chunk_received",
                "index": len(self.segments) - 1,
                "text": text,
                "speaker": speaker,
                "source": source,
                # Which placeholders the AI sees instead of the identifiers in this segment.
                "redactions": redactions,
            }
        )
        self._schedule_analysis()

    # ------------------------------------------------------------------ live analysis

    def _schedule_analysis(self) -> None:
        if not self.analysis_enabled:
            return
        self._analysis_pending = True
        if self._analysis_task is None or self._analysis_task.done():
            self._analysis_task = asyncio.create_task(self._analysis_loop())

    async def _analysis_loop(self) -> None:
        settings = get_settings()
        context_chars = settings.live_analysis_context_chars
        while self._analysis_pending:
            if self.mode == "conversation":
                # Let the person finish their thought before answering.
                await asyncio.sleep(settings.conversation_debounce_seconds)
            self._analysis_pending = False
            through_index = len(self.segments) - 1
            new_segments = [
                s for s in self.segments[self._agent_cursor : through_index + 1] if s.source != "assistant"
            ]
            self._agent_cursor = through_index + 1
            state: agent_workflow.State = {
                **self.agent_state,
                "transcript_history": self._recent_transcript(context_chars),
                "current_chunk": "\n".join(s.render() for s in new_segments),
                "case_memory": self.case_memory.text if self.case_memory else None,
            }
            context = AgentContext(
                practice_area=self.practice_area,
                document=self.document_context,
                research=self._research if self.rag_enabled else None,
                emit_status=self._emit_status,
                web_search=self._web_search if self._web_search_allowed() else None,
                mode=self.mode,
                jurisdiction=self.jurisdiction,
                lookup_authorities=self._lookup_authorities,
                intake_only=self.intake_only,
            )
            try:
                result = await agent_workflow.process_audio_chunk_via_agent(state, context)
            except Exception as exc:
                logger.exception("Agent pass failed in session %s", self.session_id)
                await self._send_error("analysis_failed", str(exc))
                continue
            await self._apply_agent_result(result, through_index)

    async def _apply_agent_result(self, result: agent_workflow.State, through_index: int) -> None:
        self.agent_state = {
            key: result[key]
            for key in ("extracted_facts", "rag_citations", "web_results", "legal_risks", "contract_observations", "follow_up_questions")
            if key in result
        }
        for error in result.get("errors", []):
            await self._send_error("agent_failed", error)

        final = result.get("final_response") or {}
        self.analysis = LiveAnalysis.model_validate(final.get("analysis") or {})
        await self._send({"type": "analysis", "through_index": through_index, "data": self.analysis.model_dump()})
        if result.get("web_results_changed"):
            await self._send(
                {"type": "web_sources", "items": final.get("web_sources", []), "queries": result.get("web_search_queries", [])}
            )
        if final.get("message"):
            masked_message = self._public_reply(final["message"])
            # Shown back to the same user, so their own details are restored for display.
            display = self.masker.unmask(masked_message)
            self.agent_message = display
            self.disclaimers_applied += int(final.get("disclaimer_appended", False))
            if self.mode == "conversation":
                self._add_assistant_turn(display, masked_message)
            await self._send(
                {
                    "type": "agent_response",
                    "through_index": through_index,
                    "message": display,
                    "disclaimer_appended": final.get("disclaimer_appended", False),
                    "spoken": self.audio_output is not None,
                    # Each citation in the message and how it checked out (services/citation_service.py).
                    "citations": final.get("citations", []),
                }
            )
            if self.audio_output is not None:
                self._start_speech(masked_message)
        await self._send({"type": "agent_status", "stage": "idle", "message": "Up to date"})

    def _public_reply(self, masked_message: str) -> str:
        """What the person hears. Public channels (phone) override this to hold legal substance."""
        return masked_message

    def _add_assistant_turn(self, display: str, masked: str) -> None:
        """A reply becomes part of the conversation the agents see next time (not new speech)."""
        self.segments.append(TranscriptSegment(display, ASSISTANT_SPEAKER, "assistant", _now().isoformat(), masked_text=masked))

    def _start_speech(self, masked_message: str) -> None:
        self._interrupt_speech()
        self._speech_task = asyncio.create_task(self._speak(masked_message))

    async def _speak(self, masked_message: str) -> None:
        # Placeholders are spoken as phrases ("the account you mentioned"), never unmasked.
        try:
            await self._send({"type": "agent_speaking", "state": "start"})
            await self.audio_output.speak(masked_message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Speech failed in session %s: %s", self.session_id, exc)
            await self._send_error("tts_failed", str(exc))
        finally:
            await self._send({"type": "agent_speaking", "state": "stop"})

    def _interrupt_speech(self) -> None:
        if self._speech_task is not None and not self._speech_task.done():
            self._speech_task.cancel()
        if self.audio_output is not None:
            self.audio_output.interrupt()

    def _web_search_allowed(self) -> bool:
        settings = get_settings()
        if not web_search.is_configured() or self._web_failures >= MAX_WEB_FAILURES:
            return False
        if self._web_searches >= settings.web_search_max_per_session:
            return False
        return not self._web_last_at or time.monotonic() - self._web_last_at >= settings.web_search_min_interval_seconds

    async def _web_search(self, queries: list[str]) -> list[WebResult] | None:
        """The external researcher's search. Queries were written to exclude client details."""
        self._web_last_at = time.monotonic()
        self._web_searches += 1
        try:
            results = await web_search.search_web(queries)
        except Exception as exc:
            self._web_failures += 1
            logger.warning("Web search failed in session %s: %s", self.session_id, exc)
            if self._web_failures >= MAX_WEB_FAILURES:
                await self._send_error("web_search_unavailable", "Live web search is unavailable for this session")
            return None
        self._web_failures = 0
        for result in results:
            self.web_sources[result.url] = result
        return results

    async def _emit_status(self, stage: str, message: str) -> None:
        await self._send({"type": "agent_status", "stage": stage, "message": message})

    async def _research(self, query: str) -> list[Precedent] | None:
        """The researcher agent's knowledge-base search, rate-limited per session.

        Returns None when skipped (too soon, too little new speech, or RAG turned off).
        """
        if not self.rag_enabled:
            return None
        settings = get_settings()
        new_chars = self.transcript_chars - self._rag_last_chars
        waited = time.monotonic() - self._rag_last_at
        if self._rag_last_at and (new_chars < settings.rag_min_new_chars or waited < settings.rag_refresh_seconds):
            return None

        self._rag_last_at = time.monotonic()
        self._rag_last_chars = self.transcript_chars
        try:
            found = await rag_service.aretrieve_relevant_precedents(
                self.org_id, query, settings.rag_top_k, db=self._db(),
                jurisdictions=self.jurisdiction.rag_codes if self.jurisdiction else None,
            )
        except Exception as exc:
            self._rag_failures += 1
            logger.warning("Knowledge-base retrieval failed in session %s: %s", self.session_id, exc)
            if self._rag_failures >= MAX_RAG_FAILURES:
                self.rag_enabled = False
                await self._send_error("rag_unavailable", "Legal citations are unavailable for this session")
            return None
        self._rag_failures = 0

        if [p.id for p in found] != [p.id for p in self.precedents]:
            self.precedents = found
            for precedent in found:
                self.matched_precedents[precedent.id] = precedent
            await self._send({"type": "citations", "items": [p.citation() for p in found]})
        return found

    def _summary_precedents(self) -> list[Precedent]:
        ranked = sorted(self.matched_precedents.values(), key=lambda p: p.similarity, reverse=True)
        return ranked[:MAX_SUMMARY_PRECEDENTS]

    def _recent_transcript(self, max_chars: int) -> str:
        """The end of the masked transcript, for the agents."""
        lines: list[str] = []
        total = 0
        for segment in reversed(self.segments):
            line = segment.render(masked=True)
            if lines and total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(reversed(lines))

    def _segment_offsets(self) -> list[dict]:
        offsets = []
        for index, segment in enumerate(self.segments):
            try:
                seconds = (datetime.fromisoformat(segment.received_at) - self.started_at).total_seconds()
            except ValueError:
                seconds = None
            offsets.append({"i": index, "speaker": segment.speaker, "source": segment.source,
                            "offset": round(seconds, 1) if seconds is not None else None})
        return offsets

    async def _lookup_authorities(self, keys: list[str], names: list[tuple[str, ...]]):
        return await run_in_threadpool(citation_service.lookup_authorities, self._db(), keys, names)

    def _citation_sources(self) -> citation_service.Sources:
        """The authority this session's agents were given (not the conversation itself)."""
        return citation_service.Sources.from_texts(
            self.case_memory.text if self.case_memory else None,
            self.document_context.text if self.document_context else None,
            jurisdiction_service.render_guidance(self.jurisdiction) if self.jurisdiction else None,
            *(f"{p.title} {p.metadata.get('citation') or ''} {p.content}" for p in self.matched_precedents.values()),
            *(f"{r.title} {r.snippet}" for r in self.web_sources.values()),
        )

    def full_transcript(self, masked: bool = False) -> str:
        return "\n".join(segment.render(masked=masked) for segment in self.segments)

    # ------------------------------------------------------------------ session end

    async def finalize(self, end_reason: str) -> None:
        """Summarize, save to Supabase, and kick off the n8n post-consultation workflow."""
        ended_at = _now()
        self._interrupt_speech()
        await self._finish_audio()
        await self._finish_analysis()
        await self._meter_audio(ended_at)

        if not self.segments:
            await self._send_session_ended(None, None, False, end_reason)
            return

        transcript = self.full_transcript()
        title, summary, summary_citations = self.title, None, []
        if self.analysis_enabled:
            try:
                result = await anthropic_service.summarize_consultation(
                    self.full_transcript(masked=True),
                    self.analysis,
                    document_context=self.document_context,
                    practice_area=self.practice_area,
                    precedents=self._summary_precedents(),
                    case_memory=self.case_memory.text if self.case_memory else None,
                    jurisdiction=self.jurisdiction,
                )
                # Citations the session's sources don't support are marked in the saved summary.
                sources = self._citation_sources()
                keys, names = citation_service.case_lookups(result.summary)
                if keys or names:
                    try:
                        sources = sources.with_known(*await self._lookup_authorities(keys, names))
                    except Exception:
                        logger.warning("Citation index lookup failed in session %s", self.session_id)
                summary, summary_citations = citation_service.verify_text(result.summary, sources)
                title = title or result.title
            except Exception as exc:
                logger.warning("Summary failed in session %s: %s", self.session_id, exc)
                await self._send_error("summary_failed", str(exc))
        title = title or f"Consultation {self.started_at:%Y-%m-%d %H:%M} UTC"

        row = {
            "title": title,
            "content": transcript,
            "summary": summary,
            "source": "live_stream",
            "org_id": self.org_id,
            "document_id": self.document_context.document_id if self.document_context else None,
            "practice_area_id": self.practice_area.id if self.practice_area else None,
            "thread_id": self.thread_id,
            "metadata": {
                "pii_redactions": self.pii_redactions,
                "mode": self.mode,
                "jurisdiction": self.jurisdiction.code if self.jurisdiction else None,
                # One entry per transcript line: when it was said, for timestamped evidence reports.
                "segments": self._segment_offsets(),
                "web_sources": [r.source() for r in self.web_sources.values()],
                "agent_message": self.agent_message,
                "disclaimers_applied": self.disclaimers_applied,
                "summary_citations": citation_service.summarize(summary_citations),
                "practice_area": self.practice_area.name if self.practice_area else None,
                "citations": [p.citation() for p in self._summary_precedents()],
                "session_id": self.session_id,
                "started_at": self.started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "end_reason": end_reason,
                "segment_count": len(self.segments),
                "analysis": self.analysis.model_dump(),
                "client_metadata": self.client_metadata,
                "consent": self.consent,
            },
        }
        try:
            saved = await self._save_transcript(row)
        except Exception:
            logger.exception("Saving transcript failed in session %s", self.session_id)
            await self._send_error("save_failed", "Could not save the transcript")
            await self._send_session_ended(None, summary, False, end_reason)
            return

        try:
            await audit_service.alog_action(
                self.user.id,
                self.org_id,
                AuditAction.END_CONSULTATION,
                "transcript",
                saved["id"],
                ip_address=self.ip_address,
                metadata={"session_id": self.session_id, "end_reason": end_reason},
            )
        except audit_service.AuditError:
            logger.error("END_CONSULTATION audit entry missing for transcript %s", saved["id"])
        await self._remember_session(saved["id"], summary)
        workflow_triggered = await self._trigger_post_consultation(saved, end_reason)
        await self._send_session_ended(saved["id"], summary, workflow_triggered, end_reason)

    async def _save_transcript(self, row: dict) -> dict:
        return await run_in_threadpool(transcript_service.save_live_session, self.user.access_token, self.user.id, row)

    async def _meter_audio(self, ended_at: datetime) -> None:
        """Bill the time audio was streamed to speech-to-text (typed-only sessions aren't metered)."""
        if not self.audio_received:
            return
        try:
            usage = await stripe_service.arecord_audio_usage(
                self.org_id, self.user.id, self.session_id, self.transport, self.started_at, ended_at,
                duration_seconds=self.audio_seconds,
            )
        except Exception:
            logger.exception("Metering audio usage failed in session %s", self.session_id)
            return
        await self._send({"type": "usage_recorded", "billed_minutes": usage.billed_minutes})

    async def _remember_session(self, transcript_id: str, summary: str | None) -> None:
        """Add this session to the case thread so the next one can recall it."""
        if not self.thread_id:
            return
        try:
            await run_in_threadpool(
                memory_service.record_session,
                self._db(),
                self.thread_id,
                transcript_id=transcript_id,
                session_id=self.session_id,
                started_at=self.started_at,
                summary=summary,
                analysis=self.analysis.model_dump(),
            )
        except Exception:
            logger.exception("Recording session %s in thread %s failed", self.session_id, self.thread_id)
            await self._send_error("memory_failed", "Transcript saved, but the case thread could not be updated")

    async def _finish_audio(self) -> None:
        """Flush Deepgram so the last words spoken before "end" make it into the transcript."""
        try:
            await self._discard_transcriber()
        except Exception:
            logger.exception("Closing transcriber failed in session %s", self.session_id)

    async def _finish_analysis(self) -> None:
        """Let in-flight analysis finish so the saved analysis covers the latest chunks."""
        if self._analysis_task is None or self._analysis_task.done():
            return
        try:
            await asyncio.wait_for(self._analysis_task, timeout=FINAL_ANALYSIS_WAIT_SECONDS)
        except Exception:
            logger.warning("Final live analysis did not finish in session %s", self.session_id)

    async def _trigger_post_consultation(self, saved: dict, end_reason: str) -> bool:
        if not n8n_service.is_configured():
            logger.info("N8N_WEBHOOK_BASE_URL not set; skipping post-consultation workflow")
            return False
        payload = {
            "event": "consultation.completed",
            "session_id": self.session_id,
            "transcript_id": saved["id"],
            "thread_id": self.thread_id,
            "org_id": self.org_id,
            "practice_area": self.practice_area.name if self.practice_area else None,
            "document_id": saved.get("document_id"),
            "user_id": self.user.id,
            "user_email": self.user.email,
            "title": saved.get("title"),
            "summary": saved.get("summary"),
            "transcript": saved.get("content"),
            "analysis": self.analysis.model_dump(),
            "started_at": self.started_at.isoformat(),
            "ended_at": saved.get("metadata", {}).get("ended_at"),
            "end_reason": end_reason,
        }
        try:
            if queue_service.is_configured():
                # The worker delivers it, retrying with backoff if n8n is down.
                await queue_service.enqueue("task_trigger_n8n_webhook", payload)
            else:
                await n8n_service.trigger_post_consultation(payload)
            return True
        except Exception as exc:
            logger.warning("n8n post-consultation trigger failed in session %s: %s", self.session_id, exc)
            await self._send_error("workflow_failed", "Transcript saved, but the post-consultation workflow failed")
            return False

    async def _send_session_ended(
        self, transcript_id: str | None, summary: str | None, workflow_triggered: bool, end_reason: str
    ) -> None:
        await self._send(
            {
                "type": "session_ended",
                "session_id": self.session_id,
                "transcript_id": transcript_id,
                "thread_id": self.thread_id,
                "summary": summary,
                "analysis": self.analysis.model_dump(),
                "workflow_triggered": workflow_triggered,
                "end_reason": end_reason,
            }
        )

    # ------------------------------------------------------------------ outbound

    async def _send(self, payload: dict) -> None:
        if not self._connected:
            return
        # The receive loop and the analysis task both send; serialize writes.
        async with self._send_lock:
            try:
                await self.ws.send_json(payload)
            except Exception:
                self._connected = False

    async def _send_error(self, code: str, message: str) -> None:
        await self._send({"type": "error", "code": code, "message": message})

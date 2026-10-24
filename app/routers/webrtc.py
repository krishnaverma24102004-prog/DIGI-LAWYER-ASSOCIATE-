"""WebRTC voice sessions: `POST /api/v1/webrtc/offer`.

The browser sends an SDP offer with one audio transceiver (sendrecv: microphone up,
AI voice down) and a data channel named "events". The server answers, then:

  microphone audio  -> 16 kHz PCM -> Deepgram speech-to-text -> agents (same live session
                       as the WebSocket, PII masking included)
  agent replies     -> Deepgram Aura TTS -> 48 kHz PCM -> the outbound audio track,
                       streamed as it is synthesized
  JSON events       <-> the data channel, using the same messages as /ws/audio
                       (agent_status, analysis, citations, web_sources, agent_response, ...,
                       and from the client: transcript_chunk, ptt, interrupt, end)

WebRTC removes the transport latency of a socket (media travels over UDP/SRTP with
jitter buffering); the time to an answer is still dominated by speech recognition, the
agents and speech synthesis. Behind strict NATs you will also need a TURN server.
"""

import asyncio
import logging
from typing import Literal
from uuid import UUID

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.rate_limiter import limit
from app.core.rbac import Permission
from app.dependencies.auth import CurrentUser, get_current_user
from app.dependencies.org import build_org_context
from app.services import audit_service, tts_service
from app.services.live_session import LiveConsultationSession
from app.services.webrtc_media import DataChannelTransport, SpeechTrack, WebRTCAudioOutput, pcm_frames

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webrtc", tags=["webrtc"])

# Live peer connections, so shutdown can close them.
_peers: set[RTCPeerConnection] = set()


class Offer(BaseModel):
    sdp: str = Field(max_length=20_000)
    type: Literal["offer"] = "offer"
    org_id: UUID | None = None
    practice_area_id: UUID | None = None
    thread_id: UUID | None = None
    mode: Literal["conversation", "copilot"] = "conversation"
    voice: bool = True
    jurisdiction: str | None = Field(default=None, max_length=10, description="IN, US, US-<state> or UK")
    consent: Literal["verbal", "written"] | None = Field(default=None, description="The client agreed to AI processing just now")


class Answer(BaseModel):
    sdp: str
    type: str
    voice: bool


def _peer_connection() -> RTCPeerConnection:
    stun = get_settings().webrtc_stun_url_list
    config = RTCConfiguration(iceServers=[RTCIceServer(urls=stun)]) if stun else RTCConfiguration(iceServers=[])
    return RTCPeerConnection(configuration=config)


@router.post("/offer", response_model=Answer, dependencies=[Depends(limit("llm"))])
async def offer(payload: Offer, request: Request, user: CurrentUser = Depends(get_current_user)):
    ctx = await run_in_threadpool(build_org_context, user, str(payload.org_id) if payload.org_id else None)
    if not ctx.can(Permission.CONSULTATION_START):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role cannot start consultations")
    if "m=audio" not in payload.sdp:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The offer must include an audio track")

    pc = _peer_connection()
    _peers.add(pc)
    transport = DataChannelTransport()
    speech = SpeechTrack()
    voice = payload.voice and tts_service.is_configured()
    session = LiveConsultationSession(
        transport,
        user,
        ctx.org_id,
        ctx.role,
        practice_area_id=str(payload.practice_area_id) if payload.practice_area_id else None,
        thread_id=str(payload.thread_id) if payload.thread_id else None,
        ip_address=audit_service.client_ip(request),
        mode=payload.mode,
        voice=voice,
        audio_output=WebRTCAudioOutput(speech),
        jurisdiction=payload.jurisdiction,
        transport="webrtc",
        consent=payload.consent,
    )
    tasks: set[asyncio.Task] = set()

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @pc.on("datachannel")
    def on_datachannel(channel):
        if channel.label == "events":
            transport.bind(channel)

    @pc.on("track")
    def on_track(track):
        if track.kind != "audio":
            return

        async def listen():
            async for pcm in pcm_frames(track):
                # The browser sends (silent) frames all session long; only speech while the mic
                # button is held goes to Deepgram, so silence is neither transcribed nor billed.
                if session.accepts_push_to_talk_audio():
                    await session.handle_pcm_audio(pcm, sample_rate=16000)

        spawn(listen())

    @pc.on("connectionstatechange")
    async def on_state_change():
        logger.info("WebRTC session %s: %s", session.session_id, pc.connectionState)
        if pc.connectionState in ("failed", "closed"):
            transport.disconnect()  # the session finalizes and saves, as on a dropped socket

    async def run_session():
        try:
            await session.run()
        finally:
            speech.stop()
            await pc.close()
            _peers.discard(pc)

    try:
        await pc.setRemoteDescription(RTCSessionDescription(sdp=payload.sdp, type="offer"))
        pc.addTrack(speech)  # attaches to the offer's audio transceiver: the AI's voice goes back on it
        await pc.setLocalDescription(await pc.createAnswer())  # waits for ICE gathering
    except Exception as exc:
        await pc.close()
        _peers.discard(pc)
        logger.warning("WebRTC negotiation failed: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not negotiate the WebRTC session") from exc

    spawn(run_session())
    return Answer(sdp=pc.localDescription.sdp, type=pc.localDescription.type, voice=voice)


async def close_all() -> None:
    await asyncio.gather(*(pc.close() for pc in list(_peers)), return_exceptions=True)
    _peers.clear()

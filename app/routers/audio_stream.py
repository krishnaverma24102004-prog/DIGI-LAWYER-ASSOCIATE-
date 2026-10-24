"""Live consultation WebSocket: `/api/v1/ws/audio`.

Authentication (Supabase access token), checked before the socket is accepted:
  * query param      `?token=<jwt>` (or `?access_token=`)
  * header           `Authorization: Bearer <jwt>`  (server-side clients)
  * subprotocol      `Sec-WebSocket-Protocol: bearer, <jwt>` (browsers can't set headers;
                     keeps the token out of URLs and access logs)

Handshake query parameters (optional):
  * `org_id`            organization to work in; defaults to the user's active org.
                        The connection is refused unless the user is a member.
  * `practice_area_id`  practice area whose prompt and risk rules drive the analysis
  * `thread_id`         case thread: earlier sessions' summaries are given to the agents,
                        and this session is added to the thread when it ends
  * `mode`              "copilot" (notes for the lawyer, default) or "conversation" (replies
                        to the user, kept as chat turns)
  * `voice`             "1" for talking mode: each reply also arrives as `agent_audio` (MP3)
  * `jurisdiction`      IN, US, US-<state> or UK: statutory framework, citation style and
                        knowledge-base filter for the agents

Client -> server (JSON text frames unless noted):
  {"type": "start", "title": "...", "metadata": {...},
   "audio": {"encoding": "linear16", "sample_rate": 16000, "channels": 1}}
      optional; send before audio. "audio" defaults to 16 kHz mono PCM; use
      {"encoding": null} for containerized audio (e.g. MediaRecorder webm/opus)
  <binary frame>                                                  raw audio -> Deepgram speech-to-text
  {"type": "transcript_chunk", "text": "...", "speaker": "Client"}  already-transcribed text
  {"type": "auth", "token": "<refreshed jwt>"}                    for sessions longer than the JWT lifetime
  {"type": "ping"}
  {"type": "ptt", "state": "start" | "stop"}                   hold-to-talk: start interrupts the AI's
                                                                speech, stop finishes the utterance now
  {"type": "interrupt"}                                         stop the AI talking
  {"type": "end"}                                                 stop: summarize, save, trigger n8n

Server -> client:
  {"type": "session_started", "session_id", "user_id", "org_id", "role"}
  {"type": "practice_area_selected", "practice_area_id", "name"}
  {"type": "case_memory_loaded", "thread_id", "title", "previous_sessions"}
  {"type": "agent_status", "stage", "message"}
      the agent working right now: intake_analyzer, legal_researcher, risk_evaluator,
      drafter; "idle" when a pass is done
  {"type": "agent_response", "through_index", "message", "disclaimer_appended", "spoken"}
      the drafter's note or reply (passed through the output-safety guardrail)
  {"type": "agent_audio", "encoding": "mp3", "audio": <base64>, "text"}   talking mode
  {"type": "agent_speaking", "state": "start" | "stop"}
  {"type": "web_sources", "items": [{title, url, snippet, published_date, score}], "queries"}
      live web results found by the external researcher when the knowledge base had nothing confident
  {"type": "citations", "items": [{id, source_id, title, citation, jurisdiction, url, similarity, excerpt}]}
      knowledge-base passages matched to the recent conversation; sent when the set changes
  {"type": "transcript_interim", "text"}                          in-progress speech, display only
  {"type": "chunk_received", "index", "text", "speaker", "source", "redactions"}
      a finalized transcript segment; `redactions` lists the placeholders the AI sees
      instead of personal identifiers in it
  {"type": "analysis", "through_index", "data": {key_facts, legal_issues, follow_up_questions}}
      full snapshot each time; replace the previous one
  {"type": "session_ended", "session_id", "transcript_id", "summary", "analysis",
   "workflow_triggered", "end_reason"}
  {"type": "error", "code", "message"}
  {"type": "pong"} / {"type": "auth_refreshed"}
"""

import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, status
from fastapi.concurrency import run_in_threadpool

from app.core.rbac import Permission, has_permission
from app.dependencies.auth import verify_access_token
from app.services import audit_service, org_service
from app.services.live_session import LiveConsultationSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audio-stream"])


def _extract_token(websocket: WebSocket) -> tuple[str | None, str | None]:
    """Return (token, subprotocol to echo back on accept)."""
    token = websocket.query_params.get("token") or websocket.query_params.get("access_token")
    if token:
        return token, None

    scheme, _, value = websocket.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip(), None

    protocols = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    if len(protocols) >= 2 and protocols[0].lower() == "bearer":
        return protocols[1], protocols[0]

    return None, None


def _uuid_param(websocket: WebSocket, name: str) -> tuple[bool, str | None]:
    """(valid, value) for an optional UUID query parameter."""
    value = websocket.query_params.get(name)
    if not value:
        return True, None
    try:
        return True, str(UUID(value))
    except ValueError:
        return False, None


@router.websocket("/ws/audio")
async def audio_stream(websocket: WebSocket) -> None:
    token, subprotocol = _extract_token(websocket)
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing access token")
        return

    try:
        user = await run_in_threadpool(verify_access_token, token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired token")
        return

    org_ok, org_id = _uuid_param(websocket, "org_id")
    area_ok, practice_area_id = _uuid_param(websocket, "practice_area_id")
    thread_ok, thread_id = _uuid_param(websocket, "thread_id")
    if not (org_ok and area_ok and thread_ok):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="org_id, practice_area_id and thread_id must be ids")
        return

    try:
        membership = await run_in_threadpool(org_service.resolve_membership, user.access_token, user.id, org_id)
    except Exception:
        logger.exception("Membership lookup failed for user %s", user.id)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Could not verify organization membership")
        return
    if membership is None or not has_permission(membership.role, Permission.CONSULTATION_START):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Not a member of this organization")
        return

    await websocket.accept(subprotocol=subprotocol)
    logger.info("Live session opened for user %s in org %s", user.id, membership.org_id)
    await LiveConsultationSession(
        websocket,
        user,
        membership.org_id,
        membership.role,
        practice_area_id=practice_area_id,
        thread_id=thread_id,
        ip_address=audit_service.client_ip(websocket),
        mode=websocket.query_params.get("mode", "copilot"),
        voice=websocket.query_params.get("voice") in ("1", "true"),
        jurisdiction=websocket.query_params.get("jurisdiction"),
        consent=websocket.query_params.get("consent"),
    ).run()

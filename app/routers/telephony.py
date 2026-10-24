"""Twilio phone intake: the voice webhook, the Media Stream socket, and number management."""

import asyncio
import json
import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from app.core import metrics
from app.core.rbac import Permission
from app.dependencies.org import OrgContext, get_org_context, require_permission
from app.database import get_supabase_admin
from app.services import audit_service, jurisdiction_service, safety_service, twilio_service
from app.services.audit_service import AuditAction
from app.services.telephony_session import TelephonySession, TwilioTransport

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telephony"])

STREAM_PATH = "/api/v1/ws/telephony"
START_TIMEOUT_SECONDS = 10
E164 = re.compile(r"^\+[1-9]\d{6,14}$")
INTAKE_OFF_MESSAGE = "Thank you for calling. This line isn't answered by our assistant right now. Please call back during office hours."


def _twiml(xml: str) -> Response:
    return Response(content=xml, media_type="application/xml")


@router.post("/telephony/voice/incoming", include_in_schema=False)
async def incoming_call(request: Request):
    """Twilio's voice webhook for the firm's numbers: connect the call to the AI intake stream."""
    if not twilio_service.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Telephony is not configured (TWILIO_AUTH_TOKEN)")
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    url = twilio_service.public_url(request.url.path, request.url.query) or str(request.url)
    if not twilio_service.verify_signature(url, params, request.headers.get("x-twilio-signature")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid Twilio signature")

    call_sid, dialled = params.get("CallSid", ""), params.get("To", "")
    number = await run_in_threadpool(twilio_service.find_number, dialled) if E164.match(dialled) else None
    if number is None:
        logger.warning("Call %s to unconfigured number %s", call_sid, dialled)
        metrics.TELEPHONY_CALLS.labels(outcome="unknown_number").inc()
        return _twiml(twilio_service.unavailable_twiml())

    if not await run_in_threadpool(safety_service.public_intake_enabled, get_supabase_admin(), number["org_id"]):
        # The firm hasn't turned on public intake: no AI on the line.
        metrics.TELEPHONY_CALLS.labels(outcome="intake_off").inc()
        return _twiml(twilio_service.unavailable_twiml(INTAKE_OFF_MESSAGE))

    stream_url = twilio_service.public_url(STREAM_PATH, scheme="wss") or str(
        request.url.replace(scheme="wss" if request.url.scheme == "https" else "ws", path=STREAM_PATH, query="")
    )
    token = twilio_service.create_stream_token(call_sid, dialled)
    return _twiml(twilio_service.connect_stream_twiml(stream_url, token, caller=params.get("From")))


async def _wait_for_start(websocket: WebSocket) -> dict | None:
    """Twilio sends "connected", then "start" with the stream's ids and custom parameters."""
    while True:
        event = json.loads(await websocket.receive_text())
        if event.get("event") == "start":
            return event.get("start") or {}
        if event.get("event") == "stop":
            return None


@router.websocket("/ws/telephony")
async def telephony_stream(websocket: WebSocket):
    """Twilio Media Stream for one call (authenticated by the signed token in the TwiML)."""
    await websocket.accept()
    try:
        start = await asyncio.wait_for(_wait_for_start(websocket), START_TIMEOUT_SECONDS)
    except Exception:  # timeout, malformed JSON or a dropped socket
        start = None
    claims = twilio_service.verify_stream_token(((start or {}).get("customParameters") or {}).get("token"))
    if start is None or claims is None or claims.call_sid != start.get("callSid"):
        metrics.TELEPHONY_CALLS.labels(outcome="rejected").inc()
        await websocket.close(code=1008)
        return
    number = await run_in_threadpool(twilio_service.find_number, claims.phone_number)
    if number is None:
        metrics.TELEPHONY_CALLS.labels(outcome="unknown_number").inc()
        await websocket.close(code=1008)
        return

    transport = TwilioTransport(websocket, start.get("streamSid", ""))
    caller = ((start.get("customParameters") or {}).get("caller")) or None
    session = TelephonySession(transport, number, call_sid=claims.call_sid, caller=caller)
    metrics.TELEPHONY_ACTIVE_CALLS.inc()
    try:
        await session.run()
        metrics.TELEPHONY_CALLS.labels(outcome="completed").inc()
    except Exception:
        metrics.TELEPHONY_CALLS.labels(outcome="failed").inc()
        logger.exception("Phone session for call %s failed", claims.call_sid)
    finally:
        metrics.TELEPHONY_ACTIVE_CALLS.dec()
        await transport.close()


# ----------------------------------------------------------------------------- numbers (RLS)


class PhoneNumber(BaseModel):
    phone_number: str = Field(description="E.164, e.g. +14155550100")
    owner_user_id: UUID | None = Field(default=None, description="Lawyer receiving the intake; defaults to you")
    practice_area_id: UUID | None = None
    jurisdiction: str | None = Field(default=None, max_length=10)
    greeting: str | None = Field(default=None, max_length=500)
    enabled: bool = True

    @field_validator("phone_number")
    @classmethod
    def _e164(cls, value: str) -> str:
        value = value.replace(" ", "")
        if not E164.match(value):
            raise ValueError("Use E.164 format, e.g. +14155550100")
        return value


@router.get("/telephony/numbers")
async def list_numbers(ctx: OrgContext = Depends(get_org_context)):
    return await run_in_threadpool(lambda: ctx.db().table("telephony_numbers").select("*").order("created_at").execute().data)


@router.post("/telephony/numbers", status_code=status.HTTP_201_CREATED)
async def add_number(
    payload: PhoneNumber, request: Request, ctx: OrgContext = Depends(require_permission(Permission.TELEPHONY_MANAGE))
):
    """Route calls to this Twilio number into the organization's AI intake."""
    try:
        jurisdiction_service.require_profile(payload.jurisdiction)
    except jurisdiction_service.UnknownJurisdiction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    row = {**payload.model_dump(mode="json"), "org_id": ctx.org_id,
           "owner_user_id": str(payload.owner_user_id or ctx.user.id)}
    try:
        saved = await run_in_threadpool(lambda: ctx.db().table("telephony_numbers").insert(row).execute().data[0])
    except Exception as exc:
        # RLS (owner must be a member) or a number already registered.
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not add this number (already registered, or invalid owner)") from exc
    await _audit(ctx, request, AuditAction.ADD_PHONE_NUMBER, payload.phone_number)
    return saved


@router.delete("/telephony/numbers/{phone_number}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_number(
    phone_number: str, request: Request, ctx: OrgContext = Depends(require_permission(Permission.TELEPHONY_MANAGE))
):
    deleted = await run_in_threadpool(
        lambda: ctx.db().table("telephony_numbers").delete().eq("phone_number", phone_number).execute().data
    )
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Number not found")
    await _audit(ctx, request, AuditAction.REMOVE_PHONE_NUMBER, phone_number)


async def _audit(ctx: OrgContext, request: Request, action: AuditAction, phone_number: str) -> None:
    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, action, "phone_number", phone_number, ip_address=audit_service.client_ip(request)
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

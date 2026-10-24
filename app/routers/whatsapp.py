"""WhatsApp intake: the Meta webhook, the firm's WhatsApp numbers, and the lawyer's inbox."""

import asyncio
import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.core.rbac import Permission
from app.dependencies.org import OrgContext, get_org_context, require_permission
from app.services import audit_service, jurisdiction_service, safety_service, whatsapp_intake, whatsapp_service
from app.services.audit_service import AuditAction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

_tasks: set[asyncio.Task] = set()


# ----------------------------------------------------------------------------- Meta webhook


@router.get("/webhook", include_in_schema=False)
def verify_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
):
    """Meta's subscription handshake: echo the challenge if the verify token matches."""
    if not whatsapp_service.verify_subscription(mode, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Verification failed")
    return Response(content=challenge, media_type="text/plain")


@router.post("/webhook", include_in_schema=False)
async def receive_webhook(request: Request):
    """Incoming messages. Answered at once; each message is processed in the background."""
    body = await request.body()
    if not whatsapp_service.verify_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON") from None
    for message in whatsapp_service.parse_messages(payload):
        task = asyncio.create_task(whatsapp_intake.handle(message))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return {"received": True}


# ----------------------------------------------------------------------------- numbers (RLS)


class WhatsAppNumber(BaseModel):
    phone_number_id: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6,20}$")]
    display_number: str = Field(description="E.164, e.g. +919876543210")
    owner_user_id: UUID | None = Field(default=None, description="Lawyer who receives the intake; defaults to you")
    practice_area_id: UUID | None = None
    jurisdiction: str | None = Field(default="IN", max_length=10)
    greeting: Annotated[str, StringConstraints(max_length=1000)] | None = None
    enabled: bool = True

    @field_validator("display_number")
    @classmethod
    def _e164(cls, value: str) -> str:
        value = value.replace(" ", "")
        if not (value.startswith("+") and value[1:].isdigit() and 8 <= len(value) <= 16):
            raise ValueError("Use E.164 format, e.g. +919876543210")
        return value


@router.get("/numbers")
async def list_numbers(ctx: OrgContext = Depends(get_org_context)):
    return await run_in_threadpool(lambda: ctx.db().table("whatsapp_numbers").select("*").execute().data)


@router.post("/numbers", status_code=status.HTTP_201_CREATED)
async def add_number(payload: WhatsAppNumber, request: Request, ctx: OrgContext = Depends(require_permission(Permission.TELEPHONY_MANAGE))):
    try:
        jurisdiction_service.require_profile(payload.jurisdiction)
    except jurisdiction_service.UnknownJurisdiction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    row = {**payload.model_dump(mode="json"), "org_id": ctx.org_id, "owner_user_id": str(payload.owner_user_id or ctx.user.id)}
    try:
        saved = await run_in_threadpool(lambda: ctx.db().table("whatsapp_numbers").upsert(row, on_conflict="phone_number_id").execute().data[0])
    except Exception as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not add this number (registered elsewhere, or invalid owner)") from exc
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, AuditAction.ADD_WHATSAPP_NUMBER, "whatsapp_number",
                                        payload.phone_number_id, ip_address=audit_service.client_ip(request))
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return saved


# ----------------------------------------------------------------------------- inbox (RLS)


class Reply(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class StatusChange(BaseModel):
    status: Literal["intake", "lawyer", "closed"]


class HeldReplyDecision(BaseModel):
    send: bool
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None  # edited wording


async def _conversation(ctx: OrgContext, conversation_id: UUID) -> dict:
    rows = await run_in_threadpool(
        lambda: ctx.db().table("whatsapp_conversations").select("*").eq("id", str(conversation_id)).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return rows[0]


@router.get("/conversations")
async def list_conversations(ctx: OrgContext = Depends(get_org_context)):
    """Chats the caller may read (the number's lawyer, owners and partners), most recent first,
    with how many AI replies in each wait for a lawyer's approval."""
    conversations = await run_in_threadpool(
        lambda: ctx.db().table("whatsapp_conversations")
        .select("id, wa_id, client_name, status, consent_at, transcript_id, last_message_at")
        .order("last_message_at", desc=True).limit(200).execute().data
    )
    held = await run_in_threadpool(
        lambda: ctx.db().table("whatsapp_messages").select("conversation_id").eq("status", "pending").execute().data
    )
    counts: dict[str, int] = {}
    for row in held:
        counts[row["conversation_id"]] = counts.get(row["conversation_id"], 0) + 1
    return [{**c, "pending_replies": counts.get(c["id"], 0)} for c in conversations]


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    conversation = await _conversation(ctx, conversation_id)
    conversation["messages"] = await run_in_threadpool(
        lambda: ctx.db().table("whatsapp_messages").select("id, direction, sender, kind, body, status, hold_reasons, reviewed_by, reviewed_at, created_at")
        .eq("conversation_id", str(conversation_id)).order("created_at").execute().data
    )
    conversation.pop("agent_state", None)
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, AuditAction.VIEW_WHATSAPP_CONVERSATION, "whatsapp_conversation",
                                        str(conversation_id), ip_address=audit_service.client_ip(request))
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return conversation


@router.post("/conversations/{conversation_id}/reply", status_code=status.HTTP_201_CREATED)
async def reply(conversation_id: UUID, payload: Reply, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Send a message as the lawyer (the AI then stays quiet in this chat)."""
    conversation = await _conversation(ctx, conversation_id)  # RLS: the caller may read it
    try:
        await whatsapp_intake.reply_as_lawyer(conversation, payload.text)
    except whatsapp_service.WhatsAppError as exc:
        # Most often: more than 24 hours since the client's last message.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, AuditAction.REPLY_WHATSAPP, "whatsapp_conversation",
                                        str(conversation_id), ip_address=audit_service.client_ip(request))
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"sent": True}


@router.post("/conversations/{conversation_id}/status")
async def change_status(conversation_id: UUID, payload: StatusChange, ctx: OrgContext = Depends(get_org_context)):
    """Hand the chat back to the AI (intake), keep it with the lawyer, or close it."""
    conversation = await _conversation(ctx, conversation_id)
    if payload.status == "intake" and not conversation.get("consent_at"):
        raise HTTPException(status.HTTP_409_CONFLICT, "The client hasn't agreed to the AI assistant yet")
    if payload.status == "intake" and not (await run_in_threadpool(safety_service.intake_status, ctx.db(), ctx.org_id))["enabled"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Public intake is turned off for the firm, so the AI can't take this chat")
    store = whatsapp_intake.Store(whatsapp_intake.get_supabase_admin())
    await run_in_threadpool(store.update, str(conversation_id), {"status": payload.status})
    return {"status": payload.status}


@router.post("/conversations/{conversation_id}/held/{message_id}")
async def settle_held_reply(
    conversation_id: UUID, message_id: UUID, payload: HeldReplyDecision, request: Request, ctx: OrgContext = Depends(get_org_context)
):
    """Send an AI reply that was held for review (as written, or with your edits), or discard it."""
    conversation = await _conversation(ctx, conversation_id)  # RLS: the caller may read it
    try:
        message = await whatsapp_intake.settle_held_reply(conversation, str(message_id), ctx.user.id, send=payload.send, text=payload.text)
    except LookupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except whatsapp_service.WhatsAppError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, AuditAction.REVIEW_HELD_REPLY, "whatsapp_message", str(message_id),
            ip_address=audit_service.client_ip(request),
            metadata={"conversation_id": str(conversation_id), "sent": payload.send, "edited": message.get("sender") == "lawyer"},
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return message

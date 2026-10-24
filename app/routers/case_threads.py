"""Case threads: one per matter, so the AI keeps context across consultations."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, StringConstraints

from app.dependencies.org import OrgContext, get_org_context
from app.routers.safety import ReasonQuery, delete_response
from app.services import audit_service, memory_service
from app.services.audit_service import AuditAction

router = APIRouter(prefix="/case-threads", tags=["case threads"])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Status = Literal["open", "closed", "archived"]


class ThreadCreate(BaseModel):
    title: Title


class ThreadUpdate(BaseModel):
    title: Title | None = None
    status: Status | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_thread(payload: ThreadCreate, ctx: OrgContext = Depends(get_org_context)):
    return await run_in_threadpool(memory_service.create_thread, ctx.db(), ctx.org_id, ctx.user.id, payload.title)


@router.get("")
async def list_threads(ctx: OrgContext = Depends(get_org_context), status_filter: Status | None = Query(None, alias="status")):
    return await run_in_threadpool(memory_service.list_threads, ctx.db(), status_filter)


@router.get("/{thread_id}")
async def get_thread(thread_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """The thread with its message history."""
    db = ctx.db()
    thread = await run_in_threadpool(memory_service.get_thread, db, str(thread_id))
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case thread not found")
    messages = await run_in_threadpool(memory_service.list_messages, db, str(thread_id))
    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, AuditAction.VIEW_CASE_THREAD, "case_thread", str(thread_id),
            ip_address=audit_service.client_ip(request),
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {**thread, "messages": messages}


@router.patch("/{thread_id}")
async def update_thread(thread_id: UUID, payload: ThreadUpdate, ctx: OrgContext = Depends(get_org_context)):
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    thread = await run_in_threadpool(memory_service.update_thread, ctx.db(), str(thread_id), changes)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case thread not found")
    return thread


@router.delete("/{thread_id}")
async def delete_thread(thread_id: UUID, request: Request, reason: ReasonQuery = None, ctx: OrgContext = Depends(get_org_context)):
    """Move to the trash (restorable for 30 days), or ask a partner or owner to (202) when your role can't."""
    thread = await run_in_threadpool(memory_service.get_thread, ctx.db(), str(thread_id))
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case thread not found")
    return await delete_response(ctx, request, "case_thread", thread_id, label=thread.get("title"), reason=reason)

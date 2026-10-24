"""Bulk document review grids: many documents x the same questions, every answer with its source."""

import asyncio
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints

from app.core.rate_limiter import limit
from app.dependencies.org import OrgContext, get_org_context
from app.routers.safety import ReasonQuery, delete_response
from app.services import audit_service, jurisdiction_service, review_service
from app.services.audit_service import AuditAction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reviews", tags=["reviews"])

# Running reviews, so they aren't garbage-collected mid-run.
_tasks: set[asyncio.Task] = set()


class Question(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    kind: str = "text"


class ReviewCreate(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    document_ids: list[UUID] = Field(min_length=1, max_length=review_service.MAX_DOCUMENTS)
    questions: list[Question] = Field(min_length=1, max_length=review_service.MAX_QUESTIONS)
    jurisdiction: str | None = Field(default=None, max_length=10)


class QuestionsAdd(BaseModel):
    questions: list[Question] = Field(min_length=1, max_length=review_service.MAX_QUESTIONS)


def _start(ctx: OrgContext, grid: dict, **kwargs) -> None:
    task = asyncio.create_task(review_service.run_review(ctx.db(), ctx.user.access_token, ctx.org_id, grid, **kwargs))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _get_or_404(ctx: OrgContext, grid_id: UUID) -> dict:
    grid = await run_in_threadpool(review_service.get_grid, ctx.db(), str(grid_id))
    if grid is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    return grid


async def _audit(ctx: OrgContext, request: Request, action: AuditAction, grid_id: str, **metadata) -> None:
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, action, "review_grid", grid_id,
                                        ip_address=audit_service.client_ip(request), metadata=metadata or None)
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/presets")
def presets():
    """Ready-made question sets (Indian commercial contracts, leases, employment, NDAs)."""
    return [{"name": name, "questions": questions} for name, questions in review_service.PRESETS.items()]


@router.post("", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(limit("llm"))])
async def create_review(payload: ReviewCreate, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Start a review. Poll `GET /reviews/{id}`: cells fill in as each document is done."""
    try:
        profile = jurisdiction_service.require_profile(payload.jurisdiction)
    except jurisdiction_service.UnknownJurisdiction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    document_ids = list(dict.fromkeys(str(d) for d in payload.document_ids))
    # RLS: only documents the caller can see.
    visible = await run_in_threadpool(
        lambda: {r["id"] for r in ctx.db().table("documents").select("id").in_("id", document_ids).execute().data}
    )
    if missing := [d for d in document_ids if d not in visible]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Documents not found: {', '.join(missing)}")
    questions = review_service.normalize_questions([q.model_dump() for q in payload.questions])
    grid = await run_in_threadpool(
        review_service.create_grid, ctx.db(), payload.title, document_ids, questions, profile.code if profile else None
    )
    await _audit(ctx, request, AuditAction.CREATE_REVIEW, grid["id"], documents=len(document_ids), questions=len(questions))
    _start(ctx, grid)
    return grid


@router.get("")
async def list_reviews(ctx: OrgContext = Depends(get_org_context)):
    return await run_in_threadpool(review_service.list_grids, ctx.db())


@router.get("/{grid_id}")
async def get_review(grid_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    return await _get_or_404(ctx, grid_id)


@router.post("/{grid_id}/questions", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(limit("llm"))])
async def add_questions(grid_id: UUID, payload: QuestionsAdd, ctx: OrgContext = Depends(get_org_context)):
    """Add columns; only the new questions are asked."""
    grid = await _get_or_404(ctx, grid_id)
    try:
        added = await run_in_threadpool(review_service.add_questions, ctx.db(), grid, [q.model_dump() for q in payload.questions])
    except review_service.ReviewError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    _start(ctx, grid, questions=added)
    return {"added": added}


@router.post("/{grid_id}/retry", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(limit("llm"))])
async def retry_failed(grid_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    """Re-run the documents that have failed cells."""
    grid = await _get_or_404(ctx, grid_id)
    failed = sorted({c["document_id"] for c in grid["cells"] if c["status"] == "error"})
    if failed:
        _start(ctx, grid, document_ids=failed)
    return {"retrying": len(failed)}


@router.get("/{grid_id}/export", response_class=Response)
async def export_review(grid_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """The grid as CSV (opens in Excel): each answer with its source passage and whether it was verified."""
    grid = await _get_or_404(ctx, grid_id)
    await _audit(ctx, request, AuditAction.EXPORT_REVIEW, grid["id"])
    return Response(
        content="﻿" + review_service.to_csv(grid),  # BOM: Excel reads it as UTF-8 (Hindi, ₹)
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{review_service.filename(grid)}"', "Cache-Control": "no-store"},
    )


@router.delete("/{grid_id}")
async def delete_review(grid_id: UUID, request: Request, reason: ReasonQuery = None, ctx: OrgContext = Depends(get_org_context)):
    """Move to the trash (restorable for 30 days), or ask a partner or owner to (202) when your role can't."""
    grid = await _get_or_404(ctx, grid_id)
    return await delete_response(ctx, request, "review_grid", grid_id, label=grid.get("title"), reason=reason)

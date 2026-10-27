"""Firm docket: deadlines, the blind second check, reminders and leave.

Every call goes through the docket's database functions as the signed-in user (migration 015),
so the checker's view is masked there and not just here. Audit rows carry statuses and an HMAC
of the inputs, never the dates (see deadline_service).
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.dependencies.org import OrgContext, get_org_context
from app.services import audit_service, deadline_service
from app.services.deadline_service import DeadlineError

router = APIRouter(prefix="/deadlines", tags=["deadlines"])

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
InputValue = date | Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class DeadlineCreate(BaseModel):
    kind: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    title: Short
    due_date: date
    owner_id: UUID | None = Field(default=None, description="Defaults to you")
    backup_id: UUID | None = Field(default=None, description="Chosen for you when left out")
    court_case_id: UUID | None = None
    thread_id: UUID | None = None
    basis: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    inputs: dict[Annotated[str, StringConstraints(max_length=80)], InputValue] = Field(default_factory=dict, max_length=20)
    candidates: list[date] = Field(default_factory=list, max_length=5)
    hard: bool = False
    safety_lead_days: int = Field(default=3, ge=0, le=60)


class CheckEntry(BaseModel):
    inputs: dict[Annotated[str, StringConstraints(max_length=80)], InputValue] = Field(default_factory=dict, max_length=20)
    due_date: date | None = Field(default=None, description="The date your inputs give (recomputed when the rule has an engine)")


class Completion(BaseModel):
    evidence: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class AbsenceCreate(BaseModel):
    starts_on: date
    ends_on: date
    user_id: UUID | None = Field(default=None, description="Defaults to you; partners and owners can record anyone's leave")
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None

    @model_validator(mode="after")
    def _order(self):
        if self.ends_on < self.starts_on:
            raise ValueError("ends_on is before starts_on")
        return self


async def _call(fn, *args, **kwargs):
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except DeadlineError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


async def _audit(ctx: OrgContext, request: Request, action: str, deadline: dict, **kwargs) -> None:
    await _call(deadline_service.audit_event, ctx.user.id, ctx.org_id, action, deadline,
                ip_address=audit_service.client_ip(request), **kwargs)


@router.get("")
async def list_deadlines(
    court_case_id: UUID | None = None, thread_id: UUID | None = None, include_done: bool = False,
    ctx: OrgContext = Depends(get_org_context),
):
    """The docket: rows awaiting your check first (without their dates), then by date."""
    return await _call(deadline_service.list_deadlines, ctx.db(), court_case_id=court_case_id, thread_id=thread_id,
                       include_done=include_done)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_deadline(payload: DeadlineCreate, ctx: OrgContext = Depends(get_org_context)):
    """Docket a deadline by hand. A second member is assigned to re-enter its inputs blind."""
    return await _call(
        deadline_service._create, ctx.db(), kind=payload.kind, title=payload.title, due_date=payload.due_date,
        owner_id=str(payload.owner_id or ctx.user.id), court_case_id=payload.court_case_id, thread_id=payload.thread_id,
        rule_id=None, rule_version=None, basis=payload.basis, inputs=payload.inputs, hard=payload.hard,
        source="manual", candidates=payload.candidates, safety_lead_days=payload.safety_lead_days,
        backup_id=payload.backup_id,
    )


@router.get("/reminders")
async def my_reminders(ctx: OrgContext = Depends(get_org_context)):
    """Your unacknowledged reminders (listing them marks them delivered)."""
    return await _call(deadline_service.my_reminders, ctx.db())


@router.post("/reminders/{reminder_id}/acknowledge")
async def acknowledge(reminder_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    result = await _call(deadline_service.acknowledge, ctx.db(), str(reminder_id))
    await _audit(ctx, request, "ACKNOWLEDGE_DEADLINE_REMINDER", {"id": result.get("deadline_id")},
                 reminder_id=str(reminder_id), acknowledged=result.get("acknowledged"))
    return result


@router.get("/absences")
async def list_absences(
    include_past: bool = Query(default=False), ctx: OrgContext = Depends(get_org_context),
):
    """Who is on leave (their reminders go to their backup meanwhile)."""

    def query():
        q = ctx.db().table("member_absences").select("id, user_id, starts_on, ends_on, note, created_by, created_at")
        if not include_past:
            q = q.gte("ends_on", date.today().isoformat())
        return q.order("starts_on").limit(500).execute().data

    return await run_in_threadpool(query)


@router.post("/absences", status_code=status.HTTP_201_CREATED)
async def add_absence(payload: AbsenceCreate, request: Request, ctx: OrgContext = Depends(get_org_context)):
    row = {"org_id": ctx.org_id, "user_id": str(payload.user_id or ctx.user.id), "starts_on": payload.starts_on.isoformat(),
           "ends_on": payload.ends_on.isoformat(), "note": payload.note}
    try:
        saved = await run_in_threadpool(lambda: ctx.db().table("member_absences").insert(row).execute().data[0])
    except Exception as exc:
        if "row-level security" in str(exc).lower() or "42501" in str(exc):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only partners and owners can record someone else's leave") from exc
        raise
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, "ADD_ABSENCE", "member_absence", saved["id"],
                                        ip_address=audit_service.client_ip(request), metadata={"user_id": row["user_id"]})
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return saved


@router.delete("/absences/{absence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_absence(absence_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    rows = await run_in_threadpool(
        lambda: ctx.db().table("member_absences").delete().eq("id", str(absence_id)).execute().data)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Absence not found")


@router.get("/{deadline_id}")
async def get_deadline(deadline_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    return await _call(deadline_service.get_deadline, ctx.db(), str(deadline_id))


@router.get("/{deadline_id}/entries")
async def entries(deadline_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    """The entries behind a deadline: only your own while its check is pending."""
    return await _call(deadline_service.deadline_entries, ctx.db(), str(deadline_id))


@router.post("/{deadline_id}/check")
async def submit_check(deadline_id: UUID, payload: CheckEntry, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Your blind re-entry. Agreement verifies the deadline; disagreement disputes it and the
    earlier date governs."""
    row, inputs, computed = await _call(deadline_service.submit_entry, ctx.db(), str(deadline_id),
                                        inputs=payload.inputs, due_date=payload.due_date)
    await _audit(ctx, request, "SUBMIT_DEADLINE_CHECK", row, inputs=inputs, computed=computed)
    return row


@router.post("/{deadline_id}/reassign-check")
async def reassign_check(deadline_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Give the check to someone else eligible (never a member who has seen the values); with
    nobody left, the maker re-enters it themselves 12 hours later."""
    row = await _call(deadline_service.reassign_check, ctx.db(), str(deadline_id))
    await _audit(ctx, request, "REASSIGN_DEADLINE_CHECK", row, check_note=row.get("check_note"))
    return row


@router.post("/{deadline_id}/complete")
async def complete(deadline_id: UUID, payload: Completion, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Mark done, with how (filing or diary number, receipt)."""
    row = await _call(deadline_service.complete, ctx.db(), str(deadline_id), payload.evidence)
    await _audit(ctx, request, "COMPLETE_DEADLINE", row)
    return row

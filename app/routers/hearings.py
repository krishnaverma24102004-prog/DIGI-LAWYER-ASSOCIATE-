"""Hearing operations: the clash board with reach estimates (P04) and hearing briefs (P47).

Everything here reads and writes through the caller's client (RLS, CLAUDE.md invariant 2). The
board covers the matters the caller can see: the whole firm for owners and partners, their own
matters for others (so a colleague's availability is only as complete as what they can see).
"""

from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints

from app.core.rate_limiter import limit
from app.dependencies.org import OrgContext, get_org_context
from app.services import audit_service, brief_service, schedule_service

router = APIRouter(prefix="/hearings", tags=["hearings"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SENIOR = ("owner", "partner")

# Audit action strings (audit_service.AuditAction is extended separately).
AUDIT_REGENERATE_BRIEF = "GENERATE_HEARING_BRIEF"
AUDIT_VIEW_BRIEF = "VIEW_HEARING_BRIEF"
AUDIT_SET_PROXY_AVAILABILITY = "SET_PROXY_AVAILABILITY"


def _today() -> date:
    return datetime.now(schedule_service.IST).date()


async def _audit(ctx: OrgContext, request: Request, action: str, resource_type: str, resource_id, metadata=None):
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, action, resource_type, str(resource_id),
                                        ip_address=audit_service.client_ip(request), metadata=metadata or {})
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


# ----------------------------------------------------------------------------- clash board


@router.get("/board")
async def board(day: date | None = Query(default=None, alias="date"), ctx: OrgContext = Depends(get_org_context)):
    """Each advocate's morning: items, reach windows, red overlaps, one amber notice, suggestions."""
    list_date = day or _today()

    def build():
        data = schedule_service.load_board(ctx.db(), list_date, org_id=ctx.org_id)
        return schedule_service.build_board(data, list_date)

    result = await run_in_threadpool(build)
    result["scope"] = "firm" if ctx.role in SENIOR else "matters you can see"
    return result


class TapIn(BaseModel):
    kind: Literal["assembled", "called", "rose"]
    item_id: UUID | str | None = None
    court_code: str | None = Field(default=None, max_length=40)
    courtroom: str | None = Field(default=None, max_length=40)
    list_date: date | None = None
    position: int | None = Field(default=None, ge=1, le=2000)
    at: datetime | None = Field(default=None, description="When it happened; defaults to now")
    court_case_id: UUID | str | None = None
    appeared_by: UUID | str | None = None


@router.post("/taps", status_code=status.HTTP_201_CREATED)
async def log_tap(payload: TapIn, ctx: OrgContext = Depends(get_org_context)):
    """'Bench assembled', 'item called' (the first call is kept) or 'court rose at item K'."""
    at = payload.at or datetime.now(timezone.utc)
    try:
        return await run_in_threadpool(
            schedule_service.record_tap, ctx.db(), user_id=ctx.user.id, kind=payload.kind,
            at=at, item_id=str(payload.item_id) if payload.item_id else None, court_code=payload.court_code,
            courtroom=payload.courtroom, list_date=payload.list_date, position=payload.position,
            court_case_id=str(payload.court_case_id) if payload.court_case_id else None,
            appeared_by=str(payload.appeared_by or ctx.user.id),
        )
    except schedule_service.ScheduleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.delete("/taps/{tap_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tap(tap_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    """Remove a mistaken tap (the person who logged it, or a partner or owner)."""
    rows = await run_in_threadpool(lambda: ctx.db().table("appearance_logs").delete().eq("id", str(tap_id)).execute().data)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tap not found, or not yours to remove")


# ----------------------------------------------------------------------------- travel times and preferences


@router.get("/travel-times")
async def travel_times(ctx: OrgContext = Depends(get_org_context)):
    rows = await run_in_threadpool(lambda: ctx.db().table("complex_travel_times").select("*").execute().data)
    return {"default_same_complex": schedule_service.SAME_COMPLEX_TRAVEL, "default_unknown": schedule_service.UNKNOWN_TRAVEL,
            "rows": sorted(rows, key=lambda r: (r["from_complex"], r["to_complex"]))}


class TravelIn(BaseModel):
    from_complex: Name
    to_complex: Name
    minutes: int = Field(ge=0, le=600)


@router.put("/travel-times")
async def set_travel_time(payload: TravelIn, ctx: OrgContext = Depends(get_org_context)):
    a, b = schedule_service.normalize_pair(payload.from_complex, payload.to_complex)
    row = {"org_id": ctx.org_id, "from_complex": a, "to_complex": b, "minutes": payload.minutes, "updated_by": ctx.user.id,
           "updated_at": datetime.now(timezone.utc).isoformat()}
    return await run_in_threadpool(
        lambda: ctx.db().table("complex_travel_times").upsert(row, on_conflict="org_id,from_complex,to_complex").execute().data[0]
    )


@router.get("/prefs")
async def prefs(ctx: OrgContext = Depends(get_org_context)):
    """Everyone's clash preferences and proxy availability in the firm, and yours."""
    rows = await run_in_threadpool(lambda: ctx.db().table("advocate_clash_prefs").select("*").execute().data)
    mine = next((r for r in rows if r["user_id"] == ctx.user.id), None)
    return {"mine": mine or {"user_id": ctx.user.id, "amber_as_clash": False, "amber_as_clash_dates": [], "enrolled": True,
                             "seniority": None},
            "members": rows}


class PrefsIn(BaseModel):
    amber_as_clash: bool | None = None
    amber_as_clash_dates: list[date] | None = Field(default=None, max_length=60)


@router.put("/prefs")
async def set_prefs(payload: PrefsIn, ctx: OrgContext = Depends(get_org_context)):
    """Treat possible clashes without data as clashes: standing, or for chosen days."""
    fields = payload.model_dump(mode="json", exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    row = {"org_id": ctx.org_id, "user_id": ctx.user.id, **fields}
    return await run_in_threadpool(
        lambda: ctx.db().table("advocate_clash_prefs").upsert(row, on_conflict="org_id,user_id").execute().data[0]
    )


class AvailabilityIn(BaseModel):
    enrolled: bool | None = None
    seniority: int | None = Field(default=None, ge=1, le=3)


@router.put("/prefs/{user_id}")
async def set_availability(user_id: UUID, payload: AvailabilityIn, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Partners and owners record who is an enrolled advocate available as a proxy, and seniority."""
    if ctx.role not in SENIOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only partners and owners set proxy availability")
    fields = payload.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    row = {"org_id": ctx.org_id, "user_id": str(user_id), **fields}
    saved = await run_in_threadpool(
        lambda: ctx.db().table("advocate_clash_prefs").upsert(row, on_conflict="org_id,user_id").execute().data[0]
    )
    await _audit(ctx, request, AUDIT_SET_PROXY_AVAILABILITY, "advocate_clash_prefs", user_id, fields)
    return saved


class CounselIn(BaseModel):
    court_case_id: UUID
    user_id: UUID
    on_vakalatnama: bool


@router.put("/counsel")
async def set_counsel(payload: CounselIn, ctx: OrgContext = Depends(get_org_context)):
    """Record whether a member is on the vakalatnama (a proxy who isn't needs a memo of appearance)."""
    row = {"org_id": ctx.org_id, **payload.model_dump(mode="json")}
    rows = await run_in_threadpool(
        lambda: ctx.db().table("case_counsel").upsert(row, on_conflict="court_case_id,user_id").execute().data
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return rows[0]


# ----------------------------------------------------------------------------- outcomes (adjournment counter)


class OutcomeIn(BaseModel):
    court_case_id: UUID
    hearing_date: date
    outcome: Literal["heard", "adjourned", "passed_over", "not_reached", "part_heard", "reserved", "disposed", "other"]
    adjourned_at_instance_of: Literal["petitioner", "respondent", "both", "court", "unknown"] | None = None
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


@router.post("/outcomes", status_code=status.HTTP_201_CREATED)
async def record_outcome(payload: OutcomeIn, ctx: OrgContext = Depends(get_org_context)):
    if payload.outcome != "adjourned" and payload.adjourned_at_instance_of:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only an adjournment is at a party's instance")
    row = {"org_id": ctx.org_id, "recorded_by": ctx.user.id, **payload.model_dump(mode="json")}
    if row["outcome"] == "adjourned" and not row["adjourned_at_instance_of"]:
        row["adjourned_at_instance_of"] = "unknown"
    rows = await run_in_threadpool(
        lambda: ctx.db().table("hearing_outcomes").upsert(row, on_conflict="court_case_id,hearing_date").execute().data
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return rows[0]


@router.get("/outcomes")
async def outcomes(court_case_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    rows = await run_in_threadpool(
        lambda: ctx.db().table("hearing_outcomes").select("*").eq("court_case_id", str(court_case_id)).execute().data
    )
    rows.sort(key=lambda r: str(r["hearing_date"]), reverse=True)
    return {"outcomes": rows, "adjournments": brief_service.adjournment_counts(rows)}


# ----------------------------------------------------------------------------- hearing briefs


@router.get("/briefs")
async def list_briefs(day: date | None = Query(default=None, alias="date"), days: int = Query(default=2, ge=0, le=30),
                      ctx: OrgContext = Depends(get_org_context)):
    """Briefs for hearings from `date` (default today) to `days` ahead."""
    start = day or _today()
    end = date.fromordinal(start.toordinal() + days)

    def load():
        rows = (ctx.db().table(brief_service.TABLE).select("id, court_case_id, hearing_date, trigger, ai_status, order_date, "
                                                            "discarded_unverified, generated_at, sections")
                .gte("hearing_date", start.isoformat()).lte("hearing_date", end.isoformat()).execute().data)
        return [{**{k: v for k, v in r.items() if k != "sections"},
                 "title": ((r.get("sections") or {}).get("case") or {}).get("title"),
                 "listing": (r.get("sections") or {}).get("listing")} for r in rows]

    rows = await run_in_threadpool(load)
    return sorted(rows, key=lambda r: (str(r["hearing_date"]), r.get("title") or ""))


@router.get("/briefs/{brief_id}")
async def get_brief(brief_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    rows = await run_in_threadpool(
        lambda: ctx.db().table(brief_service.TABLE).select("*").eq("id", str(brief_id)).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brief not found")
    await _audit(ctx, request, AUDIT_VIEW_BRIEF, "hearing_brief", brief_id)
    return rows[0]


class RegenerateIn(BaseModel):
    court_case_id: UUID
    hearing_date: date | None = Field(default=None, description="Defaults to the case's next hearing date")
    order_text: Annotated[str, StringConstraints(max_length=brief_service.MAX_ORDER_CHARS)] | None = None
    document_id: UUID | None = Field(default=None, description="An order already uploaded to the firm's documents")
    order_date: date | None = None


@router.post("/briefs/regenerate", dependencies=[Depends(limit("llm"))])
async def regenerate_brief(payload: RegenerateIn, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """(Re)build the brief for a case and hearing date, from the latest order or one you give."""
    db = ctx.db()
    cases = await run_in_threadpool(lambda: db.table("court_cases").select("*").eq("id", str(payload.court_case_id)).limit(1).execute().data)
    if not cases:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    case = cases[0]
    hearing = payload.hearing_date or (date.fromisoformat(str(case["next_hearing_date"])[:10]) if case.get("next_hearing_date") else None)
    if hearing is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the hearing date (the case has no next hearing date)")
    if payload.order_text and payload.document_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the order text or a document, not both")
    order = None
    try:
        if payload.order_text and payload.order_text.strip():
            order = brief_service.pasted_order(payload.order_text, payload.order_date)
        elif payload.document_id:
            order = await run_in_threadpool(brief_service.document_order, db, str(payload.document_id), payload.order_date)
    except brief_service.BriefError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    listing = await run_in_threadpool(_listing_for, db, case["id"], hearing)
    saved = await brief_service.generate_brief(db, case, hearing, trigger="listing_match" if listing else "manual",
                                               org_id=ctx.org_id, listing=listing, user_id=ctx.user.id, order=order)
    await _audit(ctx, request, AUDIT_REGENERATE_BRIEF, "hearing_brief", saved["id"],
                 {"court_case_id": case["id"], "hearing_date": hearing.isoformat(), "ai_status": saved["ai_status"],
                  "discarded_unverified": saved["discarded_unverified"]})
    return saved


def _listing_for(db, court_case_id: str, hearing: date) -> dict | None:
    """The case's exact cause-list match for the hearing date, if one was found."""
    matches = (db.table("listing_matches").select("id, item_id, match_type, state").eq("court_case_id", court_case_id)
               .eq("list_date", hearing.isoformat()).eq("match_type", "exact").neq("state", "dismissed").execute().data)
    for m in matches:
        items = (db.table("cause_list_items").select("*").eq("id", m["item_id"]).eq("list_date", hearing.isoformat())
                 .limit(1).execute().data)
        if items:
            return {"match_id": m["id"], "item": items[0]}
    return None

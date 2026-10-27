"""Limitation calculator and Copy tracker (P06). Dates are computed in code from signed rules; no AI.

A rule applies in a firm only once two of its members have signed its current version
(`rule_active`, migration 014). Unsigned rules can't be evaluated (422), except as an owner's or
partner's preview, which is labelled "UNVERIFIED RULE: not for reliance" and can't be docketed.
"""

from datetime import date, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.dependencies.org import OrgContext, get_org_context
from app.services import audit_service, limitation_service
from app.services.limitation_service import Calendar, Inputs, LimitationError

router = APIRouter(prefix="/limitation", tags=["limitation"])

COPY_TABLE = "copy_applications"
SENIOR_ROLES = ("owner", "partner")
CourtCode = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z0-9_-]{2,40}$")]


# ============================================================================ rules


def _signatures(ctx: OrgContext) -> list[dict]:
    return (ctx.db().table("rule_verifications").select("rule_id, version, verified_by, verified_at")
            .eq("registry", limitation_service.REGISTRY).execute().data)


@router.get("/rules")
async def list_rules(ctx: OrgContext = Depends(get_org_context)):
    """Every rule with this firm's sign-off status. Only `active` rules are offered for reliance;
    drafts need two members' signatures on their current version."""
    rows = await run_in_threadpool(_signatures, ctx)
    out = []
    for rule in limitation_service.rules().values():
        signers = {r["verified_by"]: r["verified_at"] for r in rows if r["rule_id"] == rule.rule_id and r["version"] == rule.version}
        older = any(r["rule_id"] == rule.rule_id and r["version"] < rule.version for r in rows)
        out.append({
            **rule.describe(),
            "active": len(signers) >= 2,
            "status": "active" if len(signers) >= 2 else "draft",
            "signatures": [{"verified_by": k, "verified_at": v} for k, v in sorted(signers.items(), key=lambda kv: kv[1])],
            "signed_by_me": ctx.user.id in signers,
            "signatures_needed": max(0, 2 - len(signers)),
            "earlier_version_signed": older,
        })
    return {"label": limitation_service.DISCLAIMER, "rules": out}


@router.get("/courts")
async def list_courts(ctx: OrgContext = Depends(get_org_context)):
    """Courts with a profile, for the s. 4 calendar check."""
    return await run_in_threadpool(lambda: ctx.db().table("courts").select("code, name, state").order("name").limit(1000).execute().data)


# ============================================================================ compute


class S14Period(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start: date = Field(alias="from")
    end: date = Field(alias="to")


class ComputeRequest(BaseModel):
    rule_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    start_date: date
    copy_applied_on: date | None = None
    copy_ready_on: date | None = None
    copy_delivered_on: date | None = None
    decree_copy_applied_on: date | None = None
    decree_copy_ready_on: date | None = None
    s14_periods: list[S14Period] = Field(default_factory=list, max_length=10)
    court_code: CourtCode | None = None
    filing_on: date | None = None
    copy_application_id: UUID | None = Field(default=None, description="Take the copy dates from a Copy tracker entry")
    preview: bool = Field(default=False, description="Owners and partners: evaluate a rule not yet signed off (not for reliance)")
    save_to_docket: bool = False
    owner_id: UUID | None = Field(default=None, description="Who owns the docket deadline; defaults to you")
    court_case_id: UUID | None = None
    thread_id: UUID | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] | None = None


def _rule_active(ctx: OrgContext, rule) -> bool:
    data = ctx.db().rpc("rule_active", {"p_registry": limitation_service.REGISTRY, "p_rule_id": rule.rule_id,
                                        "p_version": rule.version}).execute().data
    return data is True or data == [True] or data == "true"


def _calendar(ctx: OrgContext, court_code: str, first: date, last: date) -> Calendar:
    lo, hi = date(first.year, 1, 1), date(last.year + 1, 12, 31)
    rows = (ctx.db().table("court_calendars").select("day, closed, reason, source_url, org_id, verified_by")
            .eq("court_code", court_code).gte("day", lo.isoformat()).lte("day", hi.isoformat()).limit(5000).execute().data)
    return Calendar.from_rows(court_code, rows)


def _copy_row(ctx: OrgContext, copy_id: UUID) -> dict:
    rows = ctx.db().table(COPY_TABLE).select("*").eq("id", str(copy_id)).limit(1).execute().data
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Copy application not found")
    return rows[0]


def _evaluate(ctx: OrgContext, payload: ComputeRequest, today: date) -> tuple[dict, bool]:
    rule = limitation_service.get_rule(payload.rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown limitation rule")
    active = _rule_active(ctx, rule)
    if not active:
        if not (payload.preview and ctx.role in SENIOR_ROLES):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {
                "code": "rule_unverified",
                "message": f"'{rule.title}' (version {rule.version}) has not been signed off by two members of this firm, so it "
                           "can't be used yet" + (" (owners and partners can preview it)" if ctx.role not in SENIOR_ROLES else ""),
            })
        if payload.save_to_docket:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {
                "code": "rule_unverified", "message": "A rule that hasn't been signed off can't be saved to the docket"})

    values = payload.model_dump(include={"start_date", "copy_applied_on", "copy_ready_on", "copy_delivered_on",
                                         "decree_copy_applied_on", "decree_copy_ready_on", "filing_on"})
    values["s14_periods"] = [{"from": p.start, "to": p.end} for p in payload.s14_periods]
    court_code = payload.court_code
    if payload.copy_application_id:
        copy = _copy_row(ctx, payload.copy_application_id)
        for field, column in (("copy_applied_on", "applied_on"), ("copy_ready_on", "ready_on"), ("copy_delivered_on", "delivered_on")):
            values[field] = values.get(field) or copy.get(column)
        court_code = court_code or copy.get("court_code")
    try:
        inputs = Inputs.from_dict(values)
        # First without a calendar, to know which years' closures matter; then with them.
        draft = limitation_service.compute(rule, inputs, today=today)
        calendar = None
        if court_code:
            dates = [date.fromisoformat(draft["prescribed_end"])]
            if draft["outer_limit"]:
                dates.append(date.fromisoformat(draft["outer_limit"]["date"]))
            calendar = _calendar(ctx, court_code, min(dates), max(dates))
        result = limitation_service.compute(rule, inputs, calendar=calendar, today=today, court_code=court_code)
    except LimitationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    result["rule_active"] = active
    if not active:
        result["unverified"] = True
        result["label"] = f"{limitation_service.UNVERIFIED_LABEL}. {result['label']}"
    return result, active


@router.post("/compute")
async def compute(payload: ComputeRequest, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """The worked computation: start, period, each exclusion with its section and days, the COVID
    line, the s. 4 shift, outer limits, and the safe date (the one the docket gets)."""
    result, active = await run_in_threadpool(_evaluate, ctx, payload, date.today())
    saved: list[dict] = []
    if payload.save_to_docket:
        try:
            from app.services import deadline_service  # the docket (P13), built alongside this module
        except ImportError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The docket is not available yet") from exc
        title = payload.title or result["rule"]["title"]
        try:
            saved = await run_in_threadpool(
                limitation_service.save_to_docket, ctx.db(), result, owner_id=str(payload.owner_id or ctx.user.id), title=title,
                court_case_id=str(payload.court_case_id) if payload.court_case_id else None,
                thread_id=str(payload.thread_id) if payload.thread_id else None)
        except deadline_service.DeadlineError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        result["deadlines"] = saved
    try:
        # Ids and the rule only: never the dates or inputs.
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, "COMPUTE_LIMITATION", "limitation_rule", result["rule"]["rule_id"],
            ip_address=audit_service.client_ip(request),
            metadata={"rule_id": result["rule"]["rule_id"], "version": result["rule"]["version"], "rule_active": active,
                      "preview": not active, "deadline_ids": [d.get("id") for d in saved if isinstance(d, dict)]})
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return result


# ============================================================================ copy tracker


class CopyFields(BaseModel):
    court_case_id: UUID | None = None
    thread_id: UUID | None = None
    court_code: CourtCode | None = None
    order_date: date | None = None
    applied_on: date | None = None
    ready_on: date | None = None
    delivered_on: date | None = None
    status: Literal["pending", "ready", "delivered", "withdrawn"] | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None


class CopyCreate(CopyFields):
    applied_on: date


def _check_copy(row: dict) -> None:
    def d(key):
        value = row.get(key)
        return date.fromisoformat(str(value)[:10]) if value else None

    applied, ready, delivered, order = d("applied_on"), d("ready_on"), d("delivered_on"), d("order_date")
    if order and applied and applied < order:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The copy can't be applied for before the order")
    if ready and ready < applied:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The copy can't be ready before it was applied for")
    if delivered and delivered < (ready or applied):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The copy can't be delivered before it was ready")
    if not row.get("court_case_id") and not row.get("thread_id"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Link the copy application to a case or a case thread")


def _closed_days(ctx: OrgContext, rows: list[dict], today: date) -> dict[str, set[date]]:
    out: dict[str, set[date]] = {}
    for code in {r["court_code"] for r in rows if r.get("court_code")}:
        first = min(date.fromisoformat(str(r["applied_on"])[:10]) for r in rows if r.get("court_code") == code)
        cal = _calendar(ctx, code, first, today + timedelta(days=30))
        out[code] = set(cal.closures)
    return out


def _with_tracking(rows: list[dict], closed: dict[str, set[date]], today: date) -> list[dict]:
    return [{**r, **limitation_service.copy_status(r, today, closed.get(r.get("court_code") or "", set()))} for r in rows]


@router.get("/copy-applications")
async def list_copy_applications(
    status_: Literal["pending", "ready", "delivered", "withdrawn"] | None = Query(default=None, alias="status"),
    court_case_id: UUID | None = None,
    thread_id: UUID | None = None,
    ctx: OrgContext = Depends(get_org_context),
):
    """Certified-copy applications, oldest pending first, with days since applied and the next
    'check the copy section' date (every 3 working days while pending)."""
    today = date.today()

    def load():
        query = ctx.db().table(COPY_TABLE).select("*")
        if status_:
            query = query.eq("status", status_)
        if court_case_id:
            query = query.eq("court_case_id", str(court_case_id))
        if thread_id:
            query = query.eq("thread_id", str(thread_id))
        rows = query.order("applied_on").limit(500).execute().data
        pending = [r for r in rows if r.get("status") == "pending"]
        return _with_tracking(rows, _closed_days(ctx, pending, today), today)

    rows = await run_in_threadpool(load)
    return sorted(rows, key=lambda r: (not r["pending"], r["applied_on"]))


@router.post("/copy-applications", status_code=status.HTTP_201_CREATED)
async def add_copy_application(payload: CopyCreate, ctx: OrgContext = Depends(get_org_context)):
    row = payload.model_dump(mode="json", exclude_none=True)
    _check_copy(row)
    row["status"] = limitation_service.derive_status(row)
    saved = await run_in_threadpool(lambda: ctx.db().table(COPY_TABLE).insert(row).execute().data)
    if not saved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only link copies to cases and threads you can see")
    return _with_tracking(saved, {}, date.today())[0]


@router.patch("/copy-applications/{copy_id}")
async def update_copy_application(copy_id: UUID, payload: CopyFields, ctx: OrgContext = Depends(get_org_context)):
    current = await run_in_threadpool(_copy_row, ctx, copy_id)
    fields = payload.model_dump(mode="json", exclude_unset=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    if "applied_on" in fields and fields["applied_on"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "applied_on can't be cleared")
    merged = {**current, **fields}
    _check_copy(merged)
    fields["status"] = limitation_service.derive_status(merged)
    saved = await run_in_threadpool(lambda: ctx.db().table(COPY_TABLE).update(fields).eq("id", str(copy_id)).execute().data)
    if not saved:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't change this copy application")
    return _with_tracking(saved, {}, date.today())[0]


@router.delete("/copy-applications/{copy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_copy_application(copy_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    """Copy applications are working records: deleted outright, and only by the person who logged them."""
    current = await run_in_threadpool(_copy_row, ctx, copy_id)
    if current.get("user_id") != ctx.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the person who logged a copy application can delete it")
    deleted = await run_in_threadpool(lambda: ctx.db().table(COPY_TABLE).delete().eq("id", str(copy_id)).execute().data)
    if not deleted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the person who logged a copy application can delete it")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

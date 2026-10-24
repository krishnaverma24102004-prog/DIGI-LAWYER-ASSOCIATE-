"""Court case tracker: the firm's cases in court, hearing dates, and the upcoming-hearings agenda."""

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.core.rate_limiter import limit
from app.dependencies.org import OrgContext, get_org_context
from app.routers.safety import ReasonQuery, delete_response
from app.services import audit_service, ecourts_service
from app.services.audit_service import AuditAction

router = APIRouter(prefix="/cases", tags=["cases"])

TABLE = ecourts_service.TABLE
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class CaseFields(BaseModel):
    title: Short | None = None
    court_name: Short | None = None
    case_number: Short | None = None
    next_hearing_date: date | None = None
    client_name: Short | None = None
    client_phone: str | None = Field(default=None, description="E.164, e.g. +919876543210, for WhatsApp reminders")
    notes: Annotated[str, StringConstraints(max_length=5000)] | None = None
    thread_id: UUID | None = None

    @field_validator("client_phone")
    @classmethod
    def _e164(cls, value):
        if value in (None, ""):
            return None
        value = value.replace(" ", "").replace("-", "")
        if value.isdigit() and len(value) == 10:
            value = "+91" + value  # an Indian mobile number without the country code
        if not (value.startswith("+") and value[1:].isdigit() and 8 <= len(value) <= 16):
            raise ValueError("Use the international format, e.g. +919876543210")
        return value


class CaseCreate(CaseFields):
    cnr: str | None = Field(default=None, description="16-character eCourts CNR; fetches the case when case data is configured")


def _row(fields: CaseFields) -> dict:
    data = fields.model_dump(mode="json", exclude_unset=True)
    data.pop("cnr", None)
    return data


async def _get_or_404(ctx: OrgContext, case_id: UUID) -> dict:
    rows = await run_in_threadpool(lambda: ctx.db().table(TABLE).select("*").eq("id", str(case_id)).limit(1).execute().data)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return rows[0]


@router.get("")
async def list_cases(ctx: OrgContext = Depends(get_org_context)):
    """All cases, those with the nearest hearing first."""
    rows = await run_in_threadpool(lambda: ctx.db().table(TABLE).select("*").limit(500).execute().data)
    return sorted(rows, key=lambda c: (c.get("next_hearing_date") is None, c.get("next_hearing_date") or "", c["title"]))


@router.get("/agenda")
async def agenda(days: int = Query(default=7, ge=0, le=60), ctx: OrgContext = Depends(get_org_context)):
    """Hearings from today to `days` ahead."""
    rows = await run_in_threadpool(
        lambda: ctx.db().table(TABLE).select("id, title, court_name, case_number, next_hearing_date, client_name, cnr").execute().data
    )
    return ecourts_service.agenda(rows, date.today(), days)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_case(payload: CaseCreate, request: Request, ctx: OrgContext = Depends(get_org_context)):
    try:
        cnr = ecourts_service.normalize_cnr(payload.cnr)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    row = {**_row(payload), "cnr": cnr}
    if cnr and ecourts_service.is_configured():
        try:
            fetched = await ecourts_service.fetch_case(cnr)
        except ecourts_service.CaseDataError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        # What the lawyer typed wins over the provider's data.
        row = {**fetched, **{k: v for k, v in row.items() if v not in (None, "")}, "last_synced_at": datetime.now(timezone.utc).isoformat()}
    if not row.get("title"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the case a title (or a CNR, with case data configured)")
    try:
        saved = await run_in_threadpool(lambda: ctx.db().table(TABLE).insert(row).execute().data[0])
    except Exception as exc:
        if cnr and "duplicate" in str(exc).lower():
            raise HTTPException(status.HTTP_409_CONFLICT, "This CNR is already tracked") from exc
        raise
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, AuditAction.ADD_COURT_CASE, "court_case", saved["id"],
                                        ip_address=audit_service.client_ip(request), metadata={"cnr": cnr})
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return saved


@router.get("/{case_id}")
async def get_case(case_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    return await _get_or_404(ctx, case_id)


@router.patch("/{case_id}")
async def update_case(case_id: UUID, payload: CaseFields, ctx: OrgContext = Depends(get_org_context)):
    await _get_or_404(ctx, case_id)
    fields = _row(payload)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    return await run_in_threadpool(lambda: ctx.db().table(TABLE).update(fields).eq("id", str(case_id)).execute().data[0])


@router.post("/{case_id}/sync", dependencies=[Depends(limit("billing"))])
async def sync_case(case_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    """Refresh status and hearing dates from the case data provider."""
    case = await _get_or_404(ctx, case_id)
    if not case.get("cnr"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add the case's CNR to sync it")
    if not ecourts_service.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Case data is not configured (ECOURTS_API_KEY)")
    return await ecourts_service.sync(ctx.db(), case)


@router.delete("/{case_id}")
async def delete_case(case_id: UUID, request: Request, reason: ReasonQuery = None, ctx: OrgContext = Depends(get_org_context)):
    """Move to the trash (restorable for 30 days), or ask a partner or owner to (202) when your role can't."""
    case = await _get_or_404(ctx, case_id)
    return await delete_response(ctx, request, "court_case", case_id, label=case.get("title"), reason=reason)

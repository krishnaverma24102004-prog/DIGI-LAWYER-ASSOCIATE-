"""Tonight's board: the firm's matters in tonight's cause lists, confirmation and escalation (P05).

Reads go through the caller's RLS client. Cause lists and matches are written by the server; members
claim, dismiss, confirm and assign listings and manage the firm's advocate aliases. Setting a
matter's next hearing date from a list is a server-owned write (migration 014), made with the
service role scoped to that case and org, after the caller's own client has shown they may see it.
"""

from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.core.rate_limiter import limit
from app.database import get_supabase_admin
from app.dependencies.org import OrgContext, get_org_context
from app.services import audit_service, causelist_service, causelists

router = APIRouter(prefix="/causelists", tags=["cause lists"])

MATCHES = "listing_matches"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _audit(ctx: OrgContext, request: Request, action: str, resource_type: str, resource_id, metadata: dict | None = None):
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, action, resource_type, str(resource_id),
                                        ip_address=audit_service.client_ip(request), metadata=metadata or {})
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


async def _one(ctx: OrgContext, table: str, row_id, label: str) -> dict:
    rows = await run_in_threadpool(lambda: ctx.db().table(table).select("*").eq("id", str(row_id)).limit(1).execute().data)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found")
    return rows[0]


async def _update_match(ctx: OrgContext, match_id: UUID, fields: dict) -> dict:
    try:
        rows = await run_in_threadpool(lambda: ctx.db().table(MATCHES).update(fields).eq("id", str(match_id)).execute().data)
    except Exception as exc:
        if "not in this organization" in str(exc) or "must be members" in str(exc):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        raise
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    return rows[0]


# ----------------------------------------------------------------------------- reading


@router.get("/courts")
async def courts(ctx: OrgContext = Depends(get_org_context)):
    """Courts with a cause-list parser, and whether their lists are fetched or must be forwarded."""
    out = []
    for module in causelists.parsers().values():
        config = module.FETCHER
        out.append({
            "code": config.court_code, "name": config.name, "complex": config.complex,
            "automated_access_allowed": config.automated_access_allowed,
            "terms_url": config.terms_url, "terms_note": config.terms_note, "robots_note": config.robots_note,
            "polling": f"{config.poll_start:%H:%M}-{config.poll_end:%H:%M} IST every {config.poll_every_minutes} min",
        })
    return out


@router.get("/board")
async def board(day: Annotated[date | None, Query(alias="date")] = None, ctx: OrgContext = Depends(get_org_context)):
    """Tonight's board: listed matters by court complex and courtroom, 'possibly ours', warnings."""
    now = _now()
    target = day or causelist_service.board_date(now)
    db = ctx.db()
    result = await causelist_service.board(db, target, now)
    result["warnings"] = await causelist_service.firm_warnings(db, causelist_service.ist(now).date())
    lists = await run_in_threadpool(lambda: db.table("cause_lists")
                                    .select("id, court_code, list_type, source, source_url, filename, fetched_at, item_count, "
                                            "parse_warnings, superseded_by")
                                    .eq("list_date", target.isoformat()).execute().data)
    result["lists"] = [row for row in lists or [] if not row.get("superseded_by")]
    return result


# ----------------------------------------------------------------------------- acting on a listing


class ClaimBody(BaseModel):
    court_case_id: UUID | None = Field(default=None, description="The tracked matter this item is, if any")


class AssignBody(BaseModel):
    appearing_advocate_id: UUID | None = None
    fallback_advocate_id: UUID | None = None
    remember_fallback: bool = Field(default=False, description="Also make the fallback the matter's default")


async def _follow_list(ctx: OrgContext, match: dict) -> bool:
    """After a claim / confirmation: a matter now known to be listed tonight gets its hearing date."""
    if not match.get("court_case_id") or match["match_type"] == "exact":
        return False
    case = await _one(ctx, "court_cases", match["court_case_id"], "Case")
    item = await _one(ctx, "cause_list_items", match["item_id"], "List item")
    return await causelist_service.set_hearing_after_claim(get_supabase_admin(), match, item, case)


@router.post("/matches/{match_id}/confirm")
async def confirm(match_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Confirm appearance (stops the escalation)."""
    await _one(ctx, MATCHES, match_id, "Listing")
    match = await _update_match(ctx, match_id, {"state": "confirmed"})
    hearing = await _follow_list(ctx, match)
    await _audit(ctx, request, "CONFIRM_LISTING", "listing_match", match_id, {"hearing_date_set": hearing})
    return {**match, "hearing_date_set": match.get("hearing_date_set") or hearing}


@router.post("/matches/{match_id}/claim")
async def claim(match_id: UUID, payload: ClaimBody, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """'This is ours': optionally link the item to a tracked matter; the caller appears unless someone is assigned."""
    current = await _one(ctx, MATCHES, match_id, "Listing")
    fields: dict = {"state": "claimed"}
    if payload.court_case_id:
        await _one(ctx, "court_cases", payload.court_case_id, "Case")  # visible to the caller (RLS)
        fields["court_case_id"] = str(payload.court_case_id)
    if not current.get("appearing_advocate_id"):
        fields["appearing_advocate_id"] = ctx.user.id
    match = await _update_match(ctx, match_id, fields)
    hearing = await _follow_list(ctx, match)
    await _audit(ctx, request, "CLAIM_LISTING", "listing_match", match_id,
                 {"court_case_id": fields.get("court_case_id"), "hearing_date_set": hearing})
    return {**match, "hearing_date_set": match.get("hearing_date_set") or hearing}


@router.post("/matches/{match_id}/dismiss")
async def dismiss(match_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """'Not ours' (a 'possibly ours' item, or a probable match that is another matter)."""
    current = await _one(ctx, MATCHES, match_id, "Listing")
    if current["match_type"] == "exact" and current["state"] == "confirmed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Appearance is already confirmed for this matter")
    match = await _update_match(ctx, match_id, {"state": "dismissed"})
    await _audit(ctx, request, "DISMISS_LISTING", "listing_match", match_id)
    return match


@router.put("/matches/{match_id}/advocates")
async def assign(match_id: UUID, payload: AssignBody, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Assign the appearing and fallback advocates (members of the firm)."""
    current = await _one(ctx, MATCHES, match_id, "Listing")
    fields = {k: (str(v) if v else None) for k, v in payload.model_dump(exclude={"remember_fallback"}, exclude_unset=True).items()}
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to assign")
    match = await _update_match(ctx, match_id, fields)
    if payload.remember_fallback and current.get("court_case_id") and "fallback_advocate_id" in fields:
        await run_in_threadpool(lambda: ctx.db().table("court_cases").update({"fallback_advocate_id": fields["fallback_advocate_id"]})
                                .eq("id", current["court_case_id"]).execute())
    await _audit(ctx, request, "ASSIGN_LISTING_ADVOCATE", "listing_match", match_id, fields)
    return match


# ----------------------------------------------------------------------------- forwarded lists


@router.post("/upload", status_code=status.HTTP_201_CREATED, dependencies=[Depends(limit("billing"))])
async def upload(
    request: Request,
    court_code: Annotated[str, Form(min_length=2, max_length=40)],
    file: UploadFile = File(...),
    list_date: Annotated[date | None, Form()] = None,
    list_type: Annotated[Literal["daily", "supplementary", "advance"] | None, Form()] = None,
    ctx: OrgContext = Depends(get_org_context),
):
    """A cause-list PDF a member downloaded (a list behind a captcha, or a court we don't fetch).
    It is stored for this firm only and reconciled with the firm's matters at once."""
    code = court_code.strip().upper()
    if causelists.get_parser(code) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"No cause-list parser for {code} yet; add the hearing by hand")
    data = await file.read(causelist_service.MAX_PDF_BYTES + 1)
    try:
        result = await causelist_service.ingest_forwarded(
            get_supabase_admin(), ctx.org_id, ctx.user.id, data, court_code=code, now=_now(), list_date=list_date,
            list_type=list_type, filename=(file.filename or "")[:200] or None,
        )
    except causelist_service.CauseListError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {k: v for k, v in result.items() if not k.startswith("_")}


# ----------------------------------------------------------------------------- advocate aliases

AliasText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]


class AliasCreate(BaseModel):
    user_id: UUID
    alias: AliasText
    enrolment_no: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] | None = None

    @field_validator("alias")
    @classmethod
    def _two_words(cls, value: str) -> str:
        if len([w for w in causelists.name_tokens(value) if len(w) > 1]) < 2:
            raise ValueError("Give at least two words of the name as the list prints it (one word matches too many people)")
        return " ".join(value.split())


@router.get("/aliases")
async def list_aliases(ctx: OrgContext = Depends(get_org_context)):
    return await run_in_threadpool(lambda: ctx.db().table("advocate_aliases").select("*").order("alias").execute().data)


@router.post("/aliases", status_code=status.HTTP_201_CREATED)
async def add_alias(payload: AliasCreate, request: Request, ctx: OrgContext = Depends(get_org_context)):
    row = {"org_id": ctx.org_id, "user_id": str(payload.user_id), "alias": payload.alias, "enrolment_no": payload.enrolment_no}
    try:
        saved = await run_in_threadpool(lambda: ctx.db().table("advocate_aliases").insert(row).execute().data[0])
    except Exception as exc:
        text = str(exc).lower()
        if "duplicate" in text:
            raise HTTPException(status.HTTP_409_CONFLICT, "That alias is already on the roster") from exc
        if "row-level security" in text or "violates" in text:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Aliases are for members of this organization") from exc
        raise
    await _audit(ctx, request, "ADD_ADVOCATE_ALIAS", "advocate_alias", saved["id"], {"user_id": row["user_id"]})
    return saved


@router.delete("/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alias(alias_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    await _one(ctx, "advocate_aliases", alias_id, "Alias")
    await run_in_threadpool(lambda: ctx.db().table("advocate_aliases").delete().eq("id", str(alias_id)).execute())
    await _audit(ctx, request, "REMOVE_ADVOCATE_ALIAS", "advocate_alias", alias_id)

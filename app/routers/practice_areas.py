"""Practice areas: the firm's prompt templates and risk rules for live analysis."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from app.core.rbac import Permission
from app.dependencies.org import OrgContext, require_permission
from app.models.practice_area import PracticeArea, PracticeAreaCreate, PracticeAreaTemplate, PracticeAreaUpdate
from app.services import audit_service
from app.services.audit_service import AuditAction
from app.services.prompt_engine import BUILT_IN_TEMPLATES

router = APIRouter(prefix="/practice-areas", tags=["practice areas"])

TABLE = "practice_areas"
COLUMNS = "id, org_id, name, description, custom_system_prompt, risk_evaluation_rules, created_at, updated_at"


def _is_unique_violation(exc: Exception) -> bool:
    return "23505" in str(exc) or "duplicate key" in str(exc)


async def _audit(ctx: OrgContext, request: Request, action: AuditAction, practice_area_id: str, **meta) -> None:
    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, action, "practice_area", practice_area_id,
            ip_address=audit_service.client_ip(request), metadata=meta or None,
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/templates", response_model=list[PracticeAreaTemplate])
def list_templates():
    """Built-in starting points: Personal Injury, Corporate/M&A, Criminal Defense, Real Estate."""
    return list(BUILT_IN_TEMPLATES.values())


@router.get("", response_model=list[PracticeArea])
def list_practice_areas(ctx: OrgContext = Depends(require_permission(Permission.PRACTICE_AREAS_VIEW))):
    return ctx.db().table(TABLE).select(COLUMNS).order("name").execute().data


@router.get("/{practice_area_id}", response_model=PracticeArea)
def get_practice_area(
    practice_area_id: UUID, ctx: OrgContext = Depends(require_permission(Permission.PRACTICE_AREAS_VIEW))
):
    rows = ctx.db().table(TABLE).select(COLUMNS).eq("id", str(practice_area_id)).limit(1).execute().data
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Practice area not found")
    return rows[0]


@router.post("", response_model=PracticeArea, status_code=status.HTTP_201_CREATED)
async def create_practice_area(
    payload: PracticeAreaCreate,
    request: Request,
    ctx: OrgContext = Depends(require_permission(Permission.PRACTICE_AREAS_MANAGE)),
):
    row = {**payload.model_dump(mode="json"), "org_id": ctx.org_id, "created_by": ctx.user.id}
    try:
        saved = await run_in_threadpool(lambda: ctx.db().table(TABLE).insert(row).execute().data[0])
    except Exception as exc:
        if _is_unique_violation(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, f"A practice area named {payload.name!r} already exists") from exc
        raise
    await _audit(ctx, request, AuditAction.CREATE_PRACTICE_AREA, saved["id"], name=payload.name)
    return saved


@router.post("/install-templates", response_model=list[PracticeArea], status_code=status.HTTP_201_CREATED)
async def install_templates(
    request: Request, ctx: OrgContext = Depends(require_permission(Permission.PRACTICE_AREAS_MANAGE))
):
    """Add any built-in templates the org doesn't have yet (matched by name)."""
    db = ctx.db()
    existing = {row["name"] for row in await run_in_threadpool(lambda: db.table(TABLE).select("name").execute().data)}
    rows = [
        {**template.model_dump(mode="json"), "org_id": ctx.org_id, "created_by": ctx.user.id}
        for name, template in BUILT_IN_TEMPLATES.items()
        if name not in existing
    ]
    if not rows:
        return []
    saved = await run_in_threadpool(lambda: db.table(TABLE).insert(rows).execute().data)
    for row in saved:
        await _audit(ctx, request, AuditAction.CREATE_PRACTICE_AREA, row["id"], name=row["name"], template=True)
    return saved


@router.patch("/{practice_area_id}", response_model=PracticeArea)
async def update_practice_area(
    practice_area_id: UUID,
    payload: PracticeAreaUpdate,
    request: Request,
    ctx: OrgContext = Depends(require_permission(Permission.PRACTICE_AREAS_MANAGE)),
):
    changes = payload.model_dump(mode="json", exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    try:
        rows = await run_in_threadpool(
            lambda: ctx.db().table(TABLE).update(changes).eq("id", str(practice_area_id)).execute().data
        )
    except Exception as exc:
        if _is_unique_violation(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, "Another practice area already has that name") from exc
        raise
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Practice area not found")
    await _audit(ctx, request, AuditAction.UPDATE_PRACTICE_AREA, str(practice_area_id), fields=sorted(changes))
    return rows[0]


@router.delete("/{practice_area_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_practice_area(
    practice_area_id: UUID,
    request: Request,
    ctx: OrgContext = Depends(require_permission(Permission.PRACTICE_AREAS_MANAGE)),
):
    rows = await run_in_threadpool(lambda: ctx.db().table(TABLE).delete().eq("id", str(practice_area_id)).execute().data)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Practice area not found")
    await _audit(ctx, request, AuditAction.DELETE_PRACTICE_AREA, str(practice_area_id), name=rows[0].get("name"))

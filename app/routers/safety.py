"""Approvals, trash, legal hold and the public intake switch.

Deleting a record anywhere in the API moves it to the trash (or asks a senior; see
`safety_service.delete_record`). These routes let the firm review those requests, restore or
erase trashed records, put matters under legal hold, and turn public intake on or off.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from app.dependencies.org import OrgContext, get_org_context
from app.services import audit_service, org_service, pdf_service, safety_service
from app.services.audit_service import AuditAction
from app.services.safety_service import ApprovalRequired, SafetyError

router = APIRouter(tags=["safety"])

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
ReasonQuery = Annotated[str | None, Query(max_length=1000, description="Why it is being deleted (kept with the trash record)")]
ERASE_CONFIRMATION = "ERASE"


class Decision(BaseModel):
    note: Note | None = None


class EraseRequest(BaseModel):
    confirm: str
    reason: Note | None = None


class LegalHoldRequest(BaseModel):
    kind: Literal["case_thread", "court_case"]
    id: UUID
    hold: bool
    reason: Note | None = None


class IntakeChange(BaseModel):
    enabled: bool
    confirm: bool = False  # the caller saw what turning it on means
    reason: Note | None = None


def raise_http(exc: SafetyError) -> None:
    raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc


async def call(fn, *args, **kwargs):
    """Runs a blocking safety_service call, mapping rule violations to HTTP errors."""
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except SafetyError as exc:
        raise_http(exc)


async def audit(ctx: OrgContext, request: Request | None, action: AuditAction, resource_type: str, resource_id, **meta):
    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, action, resource_type, str(resource_id) if resource_id else None,
            ip_address=audit_service.client_ip(request) if request else None, metadata=meta or None,
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


async def delete_response(
    ctx: OrgContext, request: Request, kind: str, item_id, *, label: str | None = None, reason: str | None = None
) -> JSONResponse:
    """The response every Delete endpoint gives: 200 when trashed, 202 when a senior must approve."""
    outcome = await call(safety_service.delete_record, ctx.db(), kind, str(item_id), label=label, reason=reason)
    if outcome.status == "trashed":
        await audit(ctx, request, AuditAction.TRASH_ITEM, kind, item_id, trash_id=outcome.trash_id, title=label, reason=reason)
        return JSONResponse(outcome.as_dict(), status_code=status.HTTP_200_OK)
    await audit(ctx, request, AuditAction.REQUEST_APPROVAL, kind, item_id,
                approval_id=outcome.approval["id"], approval_action="delete", title=label)
    return JSONResponse(outcome.as_dict(), status_code=status.HTTP_202_ACCEPTED)


# ----------------------------------------------------------------------------- approvals
@router.get("/approvals")
async def list_approvals(
    status_filter: Annotated[str | None, Query(alias="status", pattern="^(pending|approved|rejected|cancelled|executed|failed)$")] = None,
    ctx: OrgContext = Depends(get_org_context),
):
    """Requests in the firm (owners and partners) or your own (associates and paralegals)."""
    return await run_in_threadpool(safety_service.list_approvals, ctx.db(), status_filter)


async def _execute(ctx: OrgContext, approval: dict) -> dict:
    """Carries out an approved request as the approver."""
    db, action, kind, target, approval_id = ctx.db(), approval["action"], approval["target_kind"], approval["target_id"], approval["id"]
    if action == "delete":
        return {"trash_id": await run_in_threadpool(safety_service.trash, db, kind, target, approval_id=approval_id)}
    if action == "enable_intake":
        return {"public_intake_enabled": await run_in_threadpool(safety_service.set_public_intake, db, True, approval_id)}
    if action == "purge":
        row = await run_in_threadpool(safety_service.erase, db, target, approval_id)
        return {"purged_at": row.get("purged_at")}
    if action == "make_owner":
        member = await run_in_threadpool(org_service.get_member, ctx.user.access_token, ctx.org_id, target)
        if member is None:
            raise SafetyError(409, "That person is no longer a member", "conflict")
        await run_in_threadpool(org_service.update_member_role, ctx.user.access_token, ctx.org_id, target, "owner")
        await run_in_threadpool(safety_service.complete, db, approval_id, True)
        return {"user_id": target, "role": "owner", "from_role": member["role"]}
    raise SafetyError(400, f"Unknown action {action}", "invalid")


@router.post("/approvals/{approval_id}/approve")
async def approve(approval_id: UUID, payload: Decision, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Approve a request and carry it out. You can't approve your own request."""
    approval = await call(safety_service.decide, ctx.db(), str(approval_id), True, payload.note)
    try:
        result = await _execute(ctx, approval)
    except SafetyError as exc:
        await run_in_threadpool(safety_service.complete, ctx.db(), str(approval_id), False, exc.message)
        await audit(ctx, request, AuditAction.APPROVE_REQUEST, "approval_request", approval_id,
                    approval_action=approval["action"], executed=False, error=exc.message)
        raise_http(exc)
    await audit(ctx, request, AuditAction.APPROVE_REQUEST, "approval_request", approval_id,
                approval_action=approval["action"], target_kind=approval["target_kind"], target_id=approval["target_id"],
                requested_by=approval.get("requested_by"), note=payload.note, executed=True, **result)
    return {**(await run_in_threadpool(safety_service.get_approval, ctx.db(), str(approval_id)) or approval), "result": result}


@router.post("/approvals/{approval_id}/reject")
async def reject(approval_id: UUID, payload: Decision, request: Request, ctx: OrgContext = Depends(get_org_context)):
    approval = await call(safety_service.decide, ctx.db(), str(approval_id), False, payload.note)
    await audit(ctx, request, AuditAction.REJECT_REQUEST, "approval_request", approval_id,
                approval_action=approval["action"], target_id=approval["target_id"], note=payload.note)
    return approval


@router.post("/approvals/{approval_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel(approval_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    """Withdraw your own pending request."""
    if not await call(safety_service.cancel, ctx.db(), str(approval_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pending request of yours with that id")


# ----------------------------------------------------------------------------- trash
@router.get("/trash")
async def list_trash(include_closed: bool = False, ctx: OrgContext = Depends(get_org_context)):
    """Deleted records that can still be restored (and, with include_closed, restored or erased ones)."""
    return await run_in_threadpool(safety_service.list_trash, ctx.db(), include_closed=include_closed)


@router.post("/trash/{trash_id}/restore")
async def restore(trash_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    row = await call(safety_service.restore, ctx.db(), str(trash_id))
    await audit(ctx, request, AuditAction.RESTORE_ITEM, row["kind"], row["item_id"], trash_id=str(trash_id), title=row.get("title"))
    return row


@router.post("/trash/{trash_id}/erase")
async def erase(trash_id: UUID, payload: EraseRequest, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Erase a trashed record now instead of after 30 days (for a client's erasure request).

    Irreversible: type ERASE to confirm. An owner asks; another owner or partner approves.
    An owner who is the firm's only partner/owner erases directly.
    """
    if payload.confirm.strip().upper() != ERASE_CONFIRMATION:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": "confirmation_required", "message": f"Type {ERASE_CONFIRMATION} to confirm"})
    item = await run_in_threadpool(safety_service.get_trash_item, ctx.db(), str(trash_id))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not in the trash")
    try:
        row = await run_in_threadpool(safety_service.erase, ctx.db(), str(trash_id))
    except ApprovalRequired as needed:
        approval = await call(safety_service.request_approval, ctx.db(), "purge", "trash_item", str(trash_id),
                              label=item.get("title"), reason=payload.reason)
        await audit(ctx, request, AuditAction.REQUEST_APPROVAL, "trash_item", trash_id, approval_id=approval["id"], approval_action="purge")
        return JSONResponse({"status": "approval_requested", "approval": approval, "message": needed.hint},
                            status_code=status.HTTP_202_ACCEPTED)
    except SafetyError as exc:
        raise_http(exc)
    await audit(ctx, request, AuditAction.ERASE_ITEM, row["kind"], row["item_id"], trash_id=str(trash_id), reason=payload.reason)
    return {"status": "erased", **row}


@router.get(
    "/trash/{trash_id}/certificate",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "Certificate of erasure"}},
)
async def erasure_certificate(trash_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """PDF record of an erased item: what was erased, who deleted and approved it, and when."""
    item = await run_in_threadpool(safety_service.get_trash_item, ctx.db(), str(trash_id))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not item.get("purged_at"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This record hasn't been erased yet")
    members = await run_in_threadpool(org_service.list_members, ctx.user.access_token, ctx.org_id)
    people = {m["user_id"]: (m.get("full_name") or m.get("email") or m["user_id"]) for m in members}
    orgs = await run_in_threadpool(org_service.list_my_organizations, ctx.user.access_token, ctx.user.id)
    org_name = next((o["name"] for o in orgs if o["id"] == ctx.org_id), ctx.org_id)
    reference = safety_service.certificate_id(item)
    pdf = await run_in_threadpool(pdf_service.build_erasure_certificate, item, org_name=org_name, people=people, reference=reference)
    await audit(ctx, request, AuditAction.EXPORT_ERASURE_CERTIFICATE, "trash_item", trash_id, reference=reference)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="erasure-certificate-{reference}.pdf"'})


# ----------------------------------------------------------------------------- legal hold
@router.put("/legal-hold")
async def set_legal_hold(payload: LegalHoldRequest, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Place or lift a legal hold on a case thread or court case (owners and partners)."""
    await call(safety_service.set_legal_hold, ctx.db(), payload.kind, str(payload.id), payload.hold, payload.reason)
    await audit(ctx, request, AuditAction.SET_LEGAL_HOLD, payload.kind, payload.id, hold=payload.hold, reason=payload.reason)
    return {"kind": payload.kind, "id": str(payload.id), "legal_hold": payload.hold}


# ----------------------------------------------------------------------------- public intake
@router.get("/intake")
async def get_intake(ctx: OrgContext = Depends(get_org_context)):
    """Whether the AI answers the firm's WhatsApp and phone numbers, and any pending request to turn it on."""
    state = await run_in_threadpool(safety_service.intake_status, ctx.db(), ctx.org_id)
    pending = [a for a in await run_in_threadpool(safety_service.list_approvals, ctx.db(), "pending")
               if a["action"] == "enable_intake"]
    return {**state, "pending_request": pending[0] if pending else None}


@router.put("/intake")
async def change_intake(payload: IntakeChange, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Turn public intake off (any owner or partner) or on (needs a second senior unless you are the only one)."""
    if payload.enabled and not payload.confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {
            "code": "confirmation_required",
            "message": "Turning on public intake lets the AI reply to anyone who messages or calls the firm's numbers. Confirm to continue.",
        })
    try:
        enabled = await run_in_threadpool(safety_service.set_public_intake, ctx.db(), payload.enabled)
    except ApprovalRequired as needed:
        approval = await call(safety_service.request_approval, ctx.db(), "enable_intake", "organization", ctx.org_id,
                              label="Turn on public intake (WhatsApp and phone)", reason=payload.reason)
        await audit(ctx, request, AuditAction.REQUEST_APPROVAL, "organization", ctx.org_id,
                    approval_id=approval["id"], approval_action="enable_intake")
        return JSONResponse({"status": "approval_requested", "approval": approval, "message": needed.hint},
                            status_code=status.HTTP_202_ACCEPTED)
    except SafetyError as exc:
        raise_http(exc)
    await audit(ctx, request, AuditAction.CHANGE_PUBLIC_INTAKE, "organization", ctx.org_id, enabled=enabled, reason=payload.reason)
    return {"status": "updated", "enabled": enabled}

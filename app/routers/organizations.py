"""Organizations, team membership and the audit log.

Org-specific routes take the org from the path. RLS enforces the same rules in the
database; the checks here give clear errors and protect each org's last owner.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints

from app.core.rbac import Permission, Role, can_manage
from app.dependencies.auth import CurrentUser, get_current_user
from app.dependencies.org import OrgContext, build_org_context
from app.database import get_supabase_for_user
from app.services import audit_service, org_service, safety_service
from app.services.audit_service import AuditAction

router = APIRouter(prefix="/organizations", tags=["organizations"])

OrgName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
RoleName = Literal["owner", "partner", "associate", "paralegal"]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class OrganizationCreate(BaseModel):
    name: OrgName


class OrganizationUpdate(BaseModel):
    name: OrgName


class MemberAdd(BaseModel):
    email: Email
    role: RoleName


class MemberUpdate(BaseModel):
    role: RoleName


async def org_from_path(org_id: UUID, user: CurrentUser = Depends(get_current_user)) -> OrgContext:
    return await run_in_threadpool(build_org_context, user, str(org_id))


def _require(ctx: OrgContext, permission: Permission) -> None:
    if not ctx.can(permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role ({ctx.role}) cannot do this ({permission.value})")


async def _audit(ctx_or_user, org_id, request: Request, action: AuditAction, resource_type: str, resource_id, **meta):
    user_id = ctx_or_user.user.id if isinstance(ctx_or_user, OrgContext) else ctx_or_user.id
    try:
        await audit_service.alog_action(
            user_id, org_id, action, resource_type, resource_id,
            ip_address=audit_service.client_ip(request), metadata=meta or None,
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


# ----------------------------------------------------------------------------- organizations


@router.get("")
async def list_organizations(user: CurrentUser = Depends(get_current_user)):
    """Organizations you belong to, with your role in each and which one is active."""
    return await run_in_threadpool(org_service.list_my_organizations, user.access_token, user.id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(payload: OrganizationCreate, request: Request, user: CurrentUser = Depends(get_current_user)):
    """Create a firm. You become its owner."""
    org = await run_in_threadpool(org_service.create_organization, user.access_token, payload.name)
    await _audit(user, org["id"], request, AuditAction.CREATE_ORGANIZATION, "organization", org["id"], name=payload.name)
    return {**org, "role": Role.OWNER.value}


@router.patch("/{org_id}")
async def update_organization(payload: OrganizationUpdate, request: Request, ctx: OrgContext = Depends(org_from_path)):
    _require(ctx, Permission.ORG_UPDATE)
    org = await run_in_threadpool(org_service.rename_organization, ctx.user.access_token, ctx.org_id, payload.name)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    await _audit(ctx, ctx.org_id, request, AuditAction.UPDATE_ORGANIZATION, "organization", ctx.org_id, name=payload.name)
    return org


@router.post("/{org_id}/activate", status_code=status.HTTP_204_NO_CONTENT)
async def activate_organization(ctx: OrgContext = Depends(org_from_path)):
    """Make this your default organization (used when a request sends no X-Org-Id)."""
    await run_in_threadpool(org_service.set_active_organization, ctx.user.access_token, ctx.user.id, ctx.org_id)


# ----------------------------------------------------------------------------- members


@router.get("/{org_id}/members")
async def list_members(ctx: OrgContext = Depends(org_from_path)):
    _require(ctx, Permission.MEMBERS_VIEW)
    return await run_in_threadpool(org_service.list_members, ctx.user.access_token, ctx.org_id)


@router.post("/{org_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(payload: MemberAdd, request: Request, ctx: OrgContext = Depends(org_from_path)):
    """Add a colleague with a role you are allowed to grant.

    Someone with an account joins now. Someone without one is invited: they join, with this
    role, when they sign up with this email (the response then has `invited: true`).
    """
    _require(ctx, Permission.MEMBERS_MANAGE)
    if not can_manage(ctx.role, payload.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"A {ctx.role} cannot grant the {payload.role} role")

    if payload.role == Role.OWNER and await run_in_threadpool(org_service.count_owners, ctx.user.access_token, ctx.org_id) > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Add them as a partner first. Making someone an owner needs a second owner's approval.",
        )

    user_id = await run_in_threadpool(org_service.find_user_id_by_email, payload.email)
    if user_id is None:
        invitation = await run_in_threadpool(org_service.create_invitation, ctx.user.access_token, ctx.org_id, payload.email, payload.role)
        await _audit(ctx, ctx.org_id, request, AuditAction.INVITE_MEMBER, "organization_invitation", invitation["id"],
                     role=payload.role)
        return {**invitation, "invited": True}
    if await run_in_threadpool(org_service.get_member, ctx.user.access_token, ctx.org_id, user_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "That user is already a member")

    member = await run_in_threadpool(org_service.add_member, ctx.user.access_token, ctx.org_id, user_id, payload.role)
    await _audit(ctx, ctx.org_id, request, AuditAction.ADD_MEMBER, "organization_member", user_id, role=payload.role)
    return member


@router.patch("/{org_id}/members/{user_id}")
async def change_member_role(user_id: UUID, payload: MemberUpdate, request: Request, ctx: OrgContext = Depends(org_from_path)):
    _require(ctx, Permission.MEMBERS_MANAGE)
    member = await run_in_threadpool(org_service.get_member, ctx.user.access_token, ctx.org_id, str(user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if not (can_manage(ctx.role, member["role"]) and can_manage(ctx.role, payload.role)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"A {ctx.role} cannot change a {member['role']} to {payload.role}")
    if member["role"] == Role.OWNER and payload.role != Role.OWNER:
        await _ensure_another_owner(ctx)
    if payload.role == Role.OWNER and member["role"] != Role.OWNER             and await run_in_threadpool(org_service.count_owners, ctx.user.access_token, ctx.org_id) > 1:
        # Owners control billing, members and erasure: with more than one owner, a second one approves.
        members = await run_in_threadpool(org_service.list_members, ctx.user.access_token, ctx.org_id)
        who = next((m.get("full_name") or m.get("email") for m in members if m["user_id"] == str(user_id)), None)
        try:
            approval = await run_in_threadpool(
                safety_service.request_approval, get_supabase_for_user(ctx.user.access_token, ctx.org_id),
                "make_owner", "organization_member", str(user_id), label=f"Make {who or 'a member'} an owner",
            )
        except safety_service.SafetyError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        await _audit(ctx, ctx.org_id, request, AuditAction.REQUEST_APPROVAL, "organization_member", str(user_id),
                     approval_id=approval["id"], approval_action="make_owner")
        return JSONResponse(
            {"status": "approval_requested", "approval": approval,
             "message": "Another owner must approve making them an owner. The request is waiting in Approvals."},
            status_code=status.HTTP_202_ACCEPTED,
        )

    updated = await run_in_threadpool(org_service.update_member_role, ctx.user.access_token, ctx.org_id, str(user_id), payload.role)
    await _audit(
        ctx, ctx.org_id, request, AuditAction.CHANGE_MEMBER_ROLE, "organization_member", str(user_id),
        from_role=member["role"], to_role=payload.role,
    )
    return updated


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: UUID, request: Request, ctx: OrgContext = Depends(org_from_path)):
    """Remove a member, or leave the organization yourself."""
    leaving = str(user_id) == ctx.user.id
    member = await run_in_threadpool(org_service.get_member, ctx.user.access_token, ctx.org_id, str(user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if not leaving:
        _require(ctx, Permission.MEMBERS_MANAGE)
        if not can_manage(ctx.role, member["role"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"A {ctx.role} cannot remove a {member['role']}")
    if member["role"] == Role.OWNER:
        await _ensure_another_owner(ctx)

    await run_in_threadpool(org_service.remove_member, ctx.user.access_token, ctx.org_id, str(user_id))
    await _audit(ctx, ctx.org_id, request, AuditAction.REMOVE_MEMBER, "organization_member", str(user_id), role=member["role"], left=leaving)


@router.get("/{org_id}/invitations")
async def list_invitations(ctx: OrgContext = Depends(org_from_path)):
    """Invitations not yet accepted (owners and partners)."""
    _require(ctx, Permission.MEMBERS_MANAGE)
    return await run_in_threadpool(org_service.list_invitations, ctx.user.access_token, ctx.org_id)


@router.delete("/{org_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(invitation_id: UUID, request: Request, ctx: OrgContext = Depends(org_from_path)):
    _require(ctx, Permission.MEMBERS_MANAGE)
    if not await run_in_threadpool(org_service.revoke_invitation, ctx.user.access_token, ctx.org_id, str(invitation_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    await _audit(ctx, ctx.org_id, request, AuditAction.REVOKE_INVITATION, "organization_invitation", str(invitation_id))


async def _ensure_another_owner(ctx: OrgContext) -> None:
    if await run_in_threadpool(org_service.count_owners, ctx.user.access_token, ctx.org_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "An organization must keep at least one owner")


# ----------------------------------------------------------------------------- audit log


@router.get("/{org_id}/audit-logs")
async def list_audit_logs(
    ctx: OrgContext = Depends(org_from_path),
    limit: int = Query(100, ge=1, le=1000),
    action: str | None = Query(None, description="Filter by action, e.g. EXPORT_PDF_REPORT"),
):
    _require(ctx, Permission.AUDIT_VIEW)
    return await run_in_threadpool(audit_service.list_audit_logs, ctx.user.access_token, ctx.org_id, limit, action)

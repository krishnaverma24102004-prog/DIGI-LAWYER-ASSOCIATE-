"""Request-scoped organization context: which org a request acts in, and the caller's role there."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from supabase import Client

from app.core.rbac import Permission, has_permission
from app.database import get_supabase_for_user
from app.dependencies.auth import CurrentUser, get_current_user
from app.services import org_service


@dataclass(frozen=True)
class OrgContext:
    user: CurrentUser
    org_id: str
    role: str

    def can(self, permission: Permission) -> bool:
        return has_permission(self.role, permission)

    def db(self) -> Client:
        """Supabase client acting as the user inside this org (RLS + x-org-id)."""
        return get_supabase_for_user(self.user.access_token, self.org_id)


def parse_org_id(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        return str(UUID(value))
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Org-Id must be an organization id") from None


def build_org_context(user: CurrentUser, requested_org_id: str | None) -> OrgContext:
    membership = org_service.resolve_membership(user.access_token, user.id, requested_org_id)
    if membership is None:
        detail = "You are not a member of this organization" if requested_org_id else "No active organization"
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail)
    return OrgContext(user=user, org_id=membership.org_id, role=membership.role)


def get_org_context(
    x_org_id: str | None = Header(default=None, description="Organization to act in; defaults to your active org"),
    user: CurrentUser = Depends(get_current_user),
) -> OrgContext:
    return build_org_context(user, parse_org_id(x_org_id))


def require_permission(permission: Permission):
    """Dependency factory: the org context, or 403 if the caller's role lacks `permission`."""

    def dependency(ctx: OrgContext = Depends(get_org_context)) -> OrgContext:
        if not ctx.can(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Your role ({ctx.role}) cannot do this ({permission.value})")
        return ctx

    return dependency

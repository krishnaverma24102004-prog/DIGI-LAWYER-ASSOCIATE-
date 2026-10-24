"""Organization membership lookups. All reads go through the user's own client (RLS)."""

from dataclasses import dataclass

from app.database import get_supabase_admin, get_supabase_for_user


@dataclass(frozen=True)
class Membership:
    org_id: str
    role: str


def resolve_membership(access_token: str, user_id: str, requested_org_id: str | None = None) -> Membership | None:
    """The org a request acts in and the caller's role there; None if they aren't a member.

    Uses `requested_org_id` (the X-Org-Id header / org_id param) when given, else the
    user's default active organization. Blocking: run in a threadpool from async code.
    """
    db = get_supabase_for_user(access_token)
    org_id = requested_org_id
    if org_id is None:
        rows = db.table("users").select("active_org_id").eq("id", user_id).limit(1).execute().data
        org_id = rows[0]["active_org_id"] if rows else None
        if org_id is None:
            return None
    rows = (
        db.table("organization_members")
        .select("role")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    )
    return Membership(org_id=org_id, role=rows[0]["role"]) if rows else None


def list_my_organizations(access_token: str, user_id: str) -> list[dict]:
    db = get_supabase_for_user(access_token)
    rows = (
        db.table("organization_members")
        .select("role, organizations(id, name, plan_tier, created_at)")
        .eq("user_id", user_id)
        .execute()
        .data
    )
    active = db.table("users").select("active_org_id").eq("id", user_id).limit(1).execute().data
    active_id = active[0]["active_org_id"] if active else None
    return [
        {**row["organizations"], "role": row["role"], "is_active": row["organizations"]["id"] == active_id}
        for row in rows
        if row.get("organizations")
    ]


def create_organization(access_token: str, name: str) -> dict:
    """Creates the org and makes the caller its owner, atomically (SQL function)."""
    return get_supabase_for_user(access_token).rpc("create_organization", {"org_name": name}).execute().data


def set_active_organization(access_token: str, user_id: str, org_id: str) -> None:
    get_supabase_for_user(access_token).table("users").update({"active_org_id": org_id}).eq("id", user_id).execute()


def rename_organization(access_token: str, org_id: str, name: str) -> dict | None:
    rows = get_supabase_for_user(access_token).table("organizations").update({"name": name}).eq("id", org_id).execute().data
    return rows[0] if rows else None


def list_members(access_token: str, org_id: str) -> list[dict]:
    db = get_supabase_for_user(access_token, org_id)
    rows = (
        db.table("organization_members")
        .select("user_id, role, created_at, users(email, full_name)")
        .eq("org_id", org_id)
        .order("created_at")
        .execute()
        .data
    )
    return [
        {
            "user_id": row["user_id"],
            "role": row["role"],
            "created_at": row["created_at"],
            "email": (row.get("users") or {}).get("email"),
            "full_name": (row.get("users") or {}).get("full_name"),
        }
        for row in rows
    ]


def get_member(access_token: str, org_id: str, user_id: str) -> dict | None:
    db = get_supabase_for_user(access_token, org_id)
    rows = db.table("organization_members").select("user_id, role").eq("org_id", org_id).eq("user_id", user_id).execute().data
    return rows[0] if rows else None


def count_owners(access_token: str, org_id: str) -> int:
    db = get_supabase_for_user(access_token, org_id)
    rows = db.table("organization_members").select("user_id").eq("org_id", org_id).eq("role", "owner").execute().data
    return len(rows)


def find_user_id_by_email(email: str) -> str | None:
    """Service-role lookup: profiles of people outside your orgs are hidden by RLS.

    Only call after the caller has been authorized to add members.
    """
    rows = get_supabase_admin().table("users").select("id").ilike("email", email.strip()).limit(1).execute().data
    return rows[0]["id"] if rows else None


def add_member(access_token: str, org_id: str, user_id: str, role: str) -> dict:
    db = get_supabase_for_user(access_token, org_id)
    return db.table("organization_members").insert({"org_id": org_id, "user_id": user_id, "role": role}).execute().data[0]


def update_member_role(access_token: str, org_id: str, user_id: str, role: str) -> dict | None:
    db = get_supabase_for_user(access_token, org_id)
    rows = (
        db.table("organization_members").update({"role": role}).eq("org_id", org_id).eq("user_id", user_id).execute().data
    )
    return rows[0] if rows else None


def remove_member(access_token: str, org_id: str, user_id: str) -> bool:
    db = get_supabase_for_user(access_token, org_id)
    rows = db.table("organization_members").delete().eq("org_id", org_id).eq("user_id", user_id).execute().data
    return bool(rows)


# ----------------------------------------------------------------------------- invitations (RLS)


def list_invitations(access_token: str, org_id: str) -> list[dict]:
    """Pending invitations: owners and partners only (RLS)."""
    db = get_supabase_for_user(access_token, org_id)
    return (
        db.table("organization_invitations")
        .select("id, email, role, created_at, expires_at")
        .eq("org_id", org_id)
        .is_("accepted_at", "null")
        .order("created_at")
        .execute()
        .data
    )


def create_invitation(access_token: str, org_id: str, email: str, role: str) -> dict:
    """Invite someone who has no account yet; they join on sign-up (migration 009). Re-inviting refreshes it."""
    db = get_supabase_for_user(access_token, org_id)
    email = email.strip().lower()
    db.table("organization_invitations").delete().eq("org_id", org_id).eq("email", email).execute()
    return db.table("organization_invitations").insert({"org_id": org_id, "email": email, "role": role}).execute().data[0]


def revoke_invitation(access_token: str, org_id: str, invitation_id: str) -> bool:
    db = get_supabase_for_user(access_token, org_id)
    return bool(db.table("organization_invitations").delete().eq("org_id", org_id).eq("id", invitation_id).execute().data)

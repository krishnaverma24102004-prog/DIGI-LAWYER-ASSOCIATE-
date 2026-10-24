"""Role-based access control for organization members.

The database enforces tenant isolation and the coarse rules with RLS (migration 004);
this module is the API's view of the same rules, used to give clear 403s up front and
to check things RLS can't express, such as protecting an organization's last owner.
"""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    PARTNER = "partner"
    ASSOCIATE = "associate"
    PARALEGAL = "paralegal"


class Permission(StrEnum):
    ORG_UPDATE = "org.update"
    MEMBERS_VIEW = "members.view"
    MEMBERS_MANAGE = "members.manage"
    PRACTICE_AREAS_VIEW = "practice_areas.view"
    PRACTICE_AREAS_MANAGE = "practice_areas.manage"
    KNOWLEDGE_VIEW = "knowledge.view"
    KNOWLEDGE_UPLOAD = "knowledge.upload"
    KNOWLEDGE_DELETE = "knowledge.delete"
    CONSULTATION_START = "consultation.start"
    TRANSCRIPTS_VIEW_ALL = "transcripts.view_all"
    DOCUMENTS_UPLOAD = "documents.upload"
    AUDIT_VIEW = "audit.view"
    BILLING_VIEW = "billing.view"
    BILLING_MANAGE = "billing.manage"
    TELEPHONY_MANAGE = "telephony.manage"


_ALL = set(Role)
_SENIOR = {Role.OWNER, Role.PARTNER}

ROLE_PERMISSIONS: dict[Permission, set[Role]] = {
    Permission.ORG_UPDATE: {Role.OWNER},
    Permission.MEMBERS_VIEW: _ALL,
    Permission.MEMBERS_MANAGE: _SENIOR,
    Permission.PRACTICE_AREAS_VIEW: _ALL,
    Permission.PRACTICE_AREAS_MANAGE: _SENIOR,
    Permission.KNOWLEDGE_VIEW: _ALL,
    Permission.KNOWLEDGE_UPLOAD: _SENIOR | {Role.ASSOCIATE},
    Permission.KNOWLEDGE_DELETE: _SENIOR,
    Permission.CONSULTATION_START: _ALL,
    Permission.TRANSCRIPTS_VIEW_ALL: _SENIOR,
    Permission.DOCUMENTS_UPLOAD: _ALL,
    Permission.AUDIT_VIEW: _SENIOR,
    Permission.BILLING_VIEW: _SENIOR,
    Permission.BILLING_MANAGE: {Role.OWNER},
    Permission.TELEPHONY_MANAGE: _SENIOR,
}

# Which roles each role may grant, change or remove.
MANAGEABLE_ROLES: dict[Role, set[Role]] = {
    Role.OWNER: _ALL,
    Role.PARTNER: {Role.ASSOCIATE, Role.PARALEGAL},
    Role.ASSOCIATE: set(),
    Role.PARALEGAL: set(),
}


def has_permission(role: Role | str | None, permission: Permission) -> bool:
    if role is None:
        return False
    try:
        return Role(role) in ROLE_PERMISSIONS[permission]
    except ValueError:
        return False


def can_manage(actor: Role | str, target: Role | str) -> bool:
    """Whether `actor` may assign the `target` role, or change/remove a member who has it."""
    try:
        return Role(target) in MANAGEABLE_ROLES[Role(actor)]
    except ValueError:
        return False

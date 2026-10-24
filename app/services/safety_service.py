"""Safety rails for a firm's own actions: trash, approvals (maker-checker), legal hold, public intake.

The rules live in the database (migration 013) so no code path can skip them; this module calls
those functions as the signed-in user and turns their errors into clear API responses.

* Deleting a record moves it to the trash for 30 days (restorable). Associates and paralegals
  deleting a client record (consultation, document, court case, case thread, knowledge source)
  create an approval request instead; a partner or owner approves and the record is trashed.
* A record under legal hold (its case thread or court case) can't be deleted.
* Enabling public intake, making someone an owner and erasing from the trash early need a
  second senior's approval, unless the caller is the firm's only owner/partner.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from postgrest.exceptions import APIError
from supabase import Client

logger = logging.getLogger(__name__)

TRASH_KINDS = ("transcript", "document", "draft", "review_grid", "court_case", "case_thread", "knowledge_source")
KIND_LABELS = {
    "transcript": "consultation",
    "document": "document",
    "draft": "draft",
    "review_grid": "review",
    "court_case": "court case",
    "case_thread": "case thread",
    "knowledge_source": "knowledge source",
}
RETENTION_DAYS = 30
TRASH_COLUMNS = (
    "id, kind, item_id, title, owner_user_id, snapshot_sha256, reason, deleted_by, deleted_at, approval_id, "
    "requested_by, purge_after, restored_at, restored_by, purged_at, purged_by"
)


class SafetyError(Exception):
    """A rule stopped the action. `status` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str, code: str = "blocked"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class ApprovalRequired(Exception):
    def __init__(self, hint: str | None):
        super().__init__(hint or "Approval required")
        self.hint = hint or "A partner or owner must approve this"


@dataclass
class DeleteOutcome:
    status: str  # "trashed" | "approval_requested"
    trash_id: str | None = None
    approval: dict | None = None
    message: str = ""

    def as_dict(self) -> dict:
        body = {"status": self.status, "message": self.message}
        if self.trash_id:
            body["trash_id"] = self.trash_id
            body["restorable_until"] = (datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)).isoformat()
        if self.approval:
            body["approval"] = self.approval
        return body


def _translate(exc: APIError) -> Exception:
    """Database rule violation -> ApprovalRequired or SafetyError."""
    code, message, hint = exc.code or "", exc.message or "", exc.hint
    if message == "approval_required":
        return ApprovalRequired(hint)
    if message == "legal_hold":
        return SafetyError(409, hint or "This record is under legal hold", "legal_hold")
    if code == "P0002":
        return SafetyError(404, message or "Not found", "not_found")
    if code == "42501":
        return SafetyError(403, message or "Not allowed", "forbidden")
    if code in ("55000", "55006", "23505", "23503"):
        return SafetyError(409, message, "conflict")
    if code == "22023":
        return SafetyError(400, message, "invalid")
    return exc


def _rpc(db: Client, name: str, params: dict):
    try:
        return db.rpc(name, params).execute().data
    except APIError as exc:
        raise _translate(exc) from exc


# ----------------------------------------------------------------------------- approvals
def request_approval(
    db: Client, action: str, target_kind: str, target_id: str, *, label: str | None = None,
    payload: dict | None = None, reason: str | None = None,
) -> dict:
    return _rpc(db, "request_approval", {
        "p_action": action, "p_target_kind": target_kind, "p_target_id": str(target_id),
        "p_target_label": label, "p_payload": payload or {}, "p_reason": reason,
    })


def list_approvals(db: Client, status: str | None = None, limit: int = 100) -> list[dict]:
    query = db.table("approval_requests").select("*").order("requested_at", desc=True).limit(limit)
    if status:
        query = query.eq("status", status)
    return query.execute().data


def get_approval(db: Client, approval_id: str) -> dict | None:
    rows = db.table("approval_requests").select("*").eq("id", approval_id).limit(1).execute().data
    return rows[0] if rows else None


def decide(db: Client, approval_id: str, approve: bool, note: str | None = None) -> dict:
    return _rpc(db, "decide_approval", {"p_id": approval_id, "p_approve": approve, "p_note": note})


def cancel(db: Client, approval_id: str) -> bool:
    return bool(_rpc(db, "cancel_approval", {"p_id": approval_id}))


def complete(db: Client, approval_id: str, ok: bool, error: str | None = None) -> bool:
    return bool(_rpc(db, "complete_approval", {"p_id": approval_id, "p_ok": ok, "p_error": error}))


# ----------------------------------------------------------------------------- trash
def trash(db: Client, kind: str, item_id: str, *, reason: str | None = None, approval_id: str | None = None) -> str:
    """Moves a record to the trash; returns the trash item id."""
    if kind not in TRASH_KINDS:
        raise SafetyError(400, f"Unknown kind {kind}", "invalid")
    return _rpc(db, "trash_item", {"p_kind": kind, "p_id": str(item_id), "p_reason": reason, "p_approval": approval_id})


def delete_record(db: Client, kind: str, item_id: str, *, label: str | None = None, reason: str | None = None) -> DeleteOutcome:
    """What a Delete button does: trash the record, or ask a senior when the caller may not."""
    noun = KIND_LABELS.get(kind, kind)
    try:
        trash_id = trash(db, kind, item_id, reason=reason)
    except ApprovalRequired as needed:
        approval = request_approval(db, "delete", kind, item_id, label=label, reason=reason)
        return DeleteOutcome(
            "approval_requested", approval=approval,
            message=f"{needed.hint}. Your request to delete this {noun} has been sent to the firm's partners and owners.",
        )
    return DeleteOutcome(
        "trashed", trash_id=trash_id,
        message=f"Moved to Trash. The {noun} can be restored for {RETENTION_DAYS} days.",
    )


def list_trash(db: Client, *, include_closed: bool = False, limit: int = 200) -> list[dict]:
    query = db.table("trash_items").select(TRASH_COLUMNS).order("deleted_at", desc=True).limit(limit)
    if not include_closed:
        query = query.is_("restored_at", "null").is_("purged_at", "null")
    return query.execute().data


def get_trash_item(db: Client, trash_id: str) -> dict | None:
    rows = db.table("trash_items").select(TRASH_COLUMNS).eq("id", trash_id).limit(1).execute().data
    return rows[0] if rows else None


def restore(db: Client, trash_id: str) -> dict:
    row = _rpc(db, "restore_trash_item", {"p_id": trash_id})
    row.pop("snapshot", None)
    return row


def erase(db: Client, trash_id: str, approval_id: str | None = None) -> dict:
    row = _rpc(db, "purge_trash_item", {"p_id": trash_id, "p_approval": approval_id})
    row.pop("snapshot", None)
    return row


def purge_expired(admin_db: Client) -> list[dict]:
    """Retention job (service role): erase snapshots older than the retention period."""
    rows = admin_db.rpc("purge_expired_trash", {}).execute().data or []
    for row in rows:
        row.pop("snapshot", None)
    return rows


def certificate_id(item: dict) -> str:
    """A stable reference for an erasure record."""
    return hashlib.sha256(f"{item['id']}:{item['purged_at']}:{item['snapshot_sha256']}".encode()).hexdigest()[:16].upper()


# ----------------------------------------------------------------------------- legal hold / intake
def set_legal_hold(db: Client, kind: str, item_id: str, hold: bool, reason: str | None = None) -> bool:
    if kind not in ("case_thread", "court_case"):
        raise SafetyError(400, "Legal hold applies to case threads and court cases", "invalid")
    return bool(_rpc(db, "set_legal_hold", {"p_kind": kind, "p_id": str(item_id), "p_hold": hold, "p_reason": reason}))


def intake_status(db: Client, org_id: str) -> dict:
    rows = (
        db.table("organizations")
        .select("public_intake_enabled, public_intake_changed_by, public_intake_changed_at")
        .eq("id", org_id).limit(1).execute().data
    )
    row = rows[0] if rows else {}
    return {
        "enabled": bool(row.get("public_intake_enabled")),
        "changed_by": row.get("public_intake_changed_by"),
        "changed_at": row.get("public_intake_changed_at"),
    }


def set_public_intake(db: Client, enabled: bool, approval_id: str | None = None) -> bool:
    return bool(_rpc(db, "set_public_intake", {"p_enabled": enabled, "p_approval": approval_id}))


def public_intake_enabled(admin_db: Client, org_id: str) -> bool:
    """For webhooks (no user session): whether the firm lets the AI answer the public."""
    rows = admin_db.table("organizations").select("public_intake_enabled").eq("id", org_id).limit(1).execute().data
    return bool(rows and rows[0].get("public_intake_enabled"))

"""Compliance audit trail.

Entries are written with the service role into public.audit_logs, which is append-only
(a trigger rejects updates and deletes) and readable by an org's owners and partners.

By default logging is fail-open: if an entry can't be written the action still
proceeds and an error is logged. Set AUDIT_FAIL_CLOSED=true to refuse audited actions
instead (log_action then raises AuditError).
"""

import ipaddress
import logging
from enum import StrEnum

from fastapi.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

from app.core.config import get_settings
from app.database import get_supabase_admin, get_supabase_for_user

logger = logging.getLogger(__name__)


class AuditAction(StrEnum):
    START_CONSULTATION = "START_CONSULTATION"
    END_CONSULTATION = "END_CONSULTATION"
    VIEW_TRANSCRIPT = "VIEW_TRANSCRIPT"
    UPLOAD_CONTRACT = "UPLOAD_CONTRACT"
    EXPORT_PDF_REPORT = "EXPORT_PDF_REPORT"
    DELETE_SESSION = "DELETE_SESSION"
    UPLOAD_KNOWLEDGE = "UPLOAD_KNOWLEDGE"
    DELETE_KNOWLEDGE = "DELETE_KNOWLEDGE"
    CREATE_ORGANIZATION = "CREATE_ORGANIZATION"
    UPDATE_ORGANIZATION = "UPDATE_ORGANIZATION"
    ADD_MEMBER = "ADD_MEMBER"
    CHANGE_MEMBER_ROLE = "CHANGE_MEMBER_ROLE"
    REMOVE_MEMBER = "REMOVE_MEMBER"
    INVITE_MEMBER = "INVITE_MEMBER"
    REVOKE_INVITATION = "REVOKE_INVITATION"
    CREATE_REVIEW = "CREATE_REVIEW"
    EXPORT_REVIEW = "EXPORT_REVIEW"
    ADD_COURT_CASE = "ADD_COURT_CASE"
    ADD_WHATSAPP_NUMBER = "ADD_WHATSAPP_NUMBER"
    REPLY_WHATSAPP = "REPLY_WHATSAPP"
    VIEW_WHATSAPP_CONVERSATION = "VIEW_WHATSAPP_CONVERSATION"
    CREATE_PRACTICE_AREA = "CREATE_PRACTICE_AREA"
    UPDATE_PRACTICE_AREA = "UPDATE_PRACTICE_AREA"
    DELETE_PRACTICE_AREA = "DELETE_PRACTICE_AREA"
    VIEW_CASE_THREAD = "VIEW_CASE_THREAD"
    DELETE_CASE_THREAD = "DELETE_CASE_THREAD"
    COMPARE_DOCUMENTS = "COMPARE_DOCUMENTS"
    ANALYZE_CONTRADICTIONS = "ANALYZE_CONTRADICTIONS"
    TRANSCRIBE_EVIDENCE = "TRANSCRIBE_EVIDENCE"
    GENERATE_DRAFT = "GENERATE_DRAFT"
    EXPORT_DRAFT = "EXPORT_DRAFT"
    APPROVE_DRAFT = "APPROVE_DRAFT"
    WITHDRAW_DRAFT_APPROVAL = "WITHDRAW_DRAFT_APPROVAL"
    START_CHECKOUT = "START_CHECKOUT"
    ADD_PHONE_NUMBER = "ADD_PHONE_NUMBER"
    REMOVE_PHONE_NUMBER = "REMOVE_PHONE_NUMBER"
    QUEUE_PDF_REPORT = "QUEUE_PDF_REPORT"
    TRASH_ITEM = "TRASH_ITEM"
    RESTORE_ITEM = "RESTORE_ITEM"
    ERASE_ITEM = "ERASE_ITEM"
    PURGE_EXPIRED_TRASH = "PURGE_EXPIRED_TRASH"
    EXPORT_ERASURE_CERTIFICATE = "EXPORT_ERASURE_CERTIFICATE"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    APPROVE_REQUEST = "APPROVE_REQUEST"
    REJECT_REQUEST = "REJECT_REQUEST"
    SET_LEGAL_HOLD = "SET_LEGAL_HOLD"
    CHANGE_PUBLIC_INTAKE = "CHANGE_PUBLIC_INTAKE"
    RECORD_CONSENT = "RECORD_CONSENT"
    REVIEW_HELD_REPLY = "REVIEW_HELD_REPLY"


class AuditError(RuntimeError):
    pass


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(connection: HTTPConnection) -> str | None:
    """The caller's IP. X-Forwarded-For is only trusted when TRUST_FORWARDED_FOR is set."""
    if get_settings().trust_forwarded_for:
        forwarded = connection.headers.get("x-forwarded-for", "")
        if forwarded:
            return _valid_ip(forwarded.split(",")[0])
    return _valid_ip(connection.client.host if connection.client else None)


def log_action(
    user_id: str | None,
    org_id: str | None,
    action: AuditAction | str,
    resource_type: str,
    resource_id: str | None = None,
    *,
    ip_address: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Append an audit entry. Blocking; returns whether it was written."""
    row = {
        "user_id": user_id,
        "org_id": org_id,
        "action": str(action),
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id is not None else None,
        "ip_address": _valid_ip(ip_address),
        "metadata": metadata or {},
    }
    try:
        get_supabase_admin().table("audit_logs").insert(row).execute()
        return True
    except Exception as exc:
        logger.error("AUDIT WRITE FAILED %s", row, exc_info=True)
        if get_settings().audit_fail_closed:
            raise AuditError("Could not record the audit entry for this action") from exc
        return False


async def alog_action(*args, **kwargs) -> bool:
    return await run_in_threadpool(log_action, *args, **kwargs)


def list_audit_logs(access_token: str, org_id: str, limit: int = 100, action: str | None = None) -> list[dict]:
    """Read through the user's client: RLS limits this to owners and partners of the org."""
    query = get_supabase_for_user(access_token, org_id).table("audit_logs").select("*").eq("org_id", org_id)
    if action:
        query = query.eq("action", action)
    return query.order("timestamp", desc=True).limit(limit).execute().data

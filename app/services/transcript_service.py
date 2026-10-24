"""Transcript data access. Expects a user-scoped client so RLS enforces ownership."""

import logging

from supabase import Client

from app.database import get_supabase_admin, get_supabase_for_user
from app.models.transcript import TranscriptCreate, TranscriptUpdate

logger = logging.getLogger(__name__)

TABLE = "transcripts"


def save_live_session(access_token: str, user_id: str, row: dict) -> dict:
    """Insert a finished live-session transcript. Blocking: call via a threadpool from async code.

    Tries the user's own client first so RLS applies. A long consultation can outlive
    the user's JWT; since user_id and org membership were verified when the socket
    connected, fall back to the service role with user_id and org_id set explicitly.
    """
    row = {**row, "user_id": user_id}
    try:
        return get_supabase_for_user(access_token, row.get("org_id")).table(TABLE).insert(row).execute().data[0]
    except Exception:
        logger.warning("User-scoped insert failed for user %s; retrying with service role", user_id, exc_info=True)
        return get_supabase_admin().table(TABLE).insert(row).execute().data[0]


def list_transcripts(db: Client) -> list[dict]:
    return db.table(TABLE).select("*").order("created_at", desc=True).execute().data


def get_transcript(db: Client, transcript_id: str) -> dict | None:
    rows = db.table(TABLE).select("*").eq("id", transcript_id).limit(1).execute().data
    return rows[0] if rows else None


def create_transcript(db: Client, user_id: str, payload: TranscriptCreate) -> dict:
    row = {**payload.model_dump(), "user_id": user_id}
    return db.table(TABLE).insert(row).execute().data[0]


def update_transcript(db: Client, transcript_id: str, payload: TranscriptUpdate) -> dict | None:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return get_transcript(db, transcript_id)
    rows = db.table(TABLE).update(changes).eq("id", transcript_id).execute().data
    return rows[0] if rows else None

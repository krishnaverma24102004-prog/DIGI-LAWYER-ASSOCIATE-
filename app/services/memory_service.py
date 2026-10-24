"""Persistent case memory across consultations.

A case thread groups the sessions of one matter. When a session ends, its summary,
key facts and risks are stored as a `session_summary` message. When a later session
joins the thread, the recent summaries become the agents' case history, so the AI
remembers what the client said last week.

Everything stored here was produced from PII-masked text (summaries are generated
from the masked transcript), so the case history sent to Claude stays masked too.
All access goes through the user's client in their org: RLS decides who sees a thread.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from supabase import Client

from app.core.config import get_settings

THREADS = "case_threads"
MESSAGES = "thread_messages"
THREAD_COLUMNS = ("id, user_id, org_id, title, status, legal_hold, legal_hold_reason, ai_consent_at, ai_consent_by, "
                  "ai_consent_method, created_at, updated_at")


@dataclass(frozen=True)
class CaseMemory:
    thread_id: str
    title: str
    text: str
    session_count: int


# ----------------------------------------------------------------------------- threads


def create_thread(db: Client, org_id: str, user_id: str, title: str) -> dict:
    row = {"org_id": org_id, "user_id": user_id, "title": title.strip()[:200]}
    return db.table(THREADS).insert(row).execute().data[0]


def list_threads(db: Client, status: str | None = None) -> list[dict]:
    query = db.table(THREADS).select(THREAD_COLUMNS)
    if status:
        query = query.eq("status", status)
    return query.order("updated_at", desc=True).execute().data


def get_thread(db: Client, thread_id: str) -> dict | None:
    rows = db.table(THREADS).select(THREAD_COLUMNS).eq("id", thread_id).limit(1).execute().data
    return rows[0] if rows else None


def update_thread(db: Client, thread_id: str, changes: dict) -> dict | None:
    rows = db.table(THREADS).update(changes).eq("id", thread_id).execute().data
    return rows[0] if rows else None


# ----------------------------------------------------------------------------- messages


def add_message(db: Client, thread_id: str, role: str, content: str, metadata: dict | None = None) -> dict:
    row = {"thread_id": thread_id, "role": role, "content": content, "metadata": metadata or {}}
    return db.table(MESSAGES).insert(row).execute().data[0]


def list_messages(db: Client, thread_id: str, limit: int = 200) -> list[dict]:
    return (
        db.table(MESSAGES)
        .select("id, role, content, metadata, created_at")
        .eq("thread_id", thread_id)
        .order("created_at")
        .limit(limit)
        .execute()
        .data
    )


def record_session(
    db: Client,
    thread_id: str,
    *,
    transcript_id: str,
    session_id: str,
    started_at: datetime,
    summary: str | None,
    analysis: dict,
) -> dict:
    """Store what later sessions should remember about this one."""
    facts = [f.get("fact") for f in analysis.get("key_facts", []) if f.get("fact")]
    issues = [
        f"{i.get('issue')} ({i.get('severity', 'medium')})" for i in analysis.get("legal_issues", []) if i.get("issue")
    ]
    content = summary or _fallback_summary(facts, issues)
    message = add_message(
        db,
        thread_id,
        "session_summary",
        content,
        {
            "transcript_id": transcript_id,
            "session_id": session_id,
            "started_at": started_at.isoformat(),
            "key_facts": facts,
            "legal_issues": issues,
            "open_questions": analysis.get("follow_up_questions", []),
        },
    )
    # Bump updated_at so recently active cases sort first.
    update_thread(db, thread_id, {"updated_at": datetime.now(timezone.utc).isoformat()})
    return message


def _fallback_summary(facts: list[str], issues: list[str]) -> str:
    parts = []
    if facts:
        parts.append("Key facts: " + "; ".join(facts))
    if issues:
        parts.append("Issues flagged: " + "; ".join(issues))
    return "\n".join(parts) or "Session recorded; no summary available."


# ----------------------------------------------------------------------------- recall


def load_case_memory(db: Client, thread_id: str, max_sessions: int | None = None, max_chars: int | None = None) -> CaseMemory | None:
    """The thread's most recent session summaries, oldest first, within a size budget.

    None if the thread doesn't exist or the user can't see it.
    """
    settings = get_settings()
    max_sessions = max_sessions or settings.case_memory_max_sessions
    max_chars = max_chars or settings.case_memory_max_chars

    thread = get_thread(db, thread_id)
    if thread is None:
        return None
    rows = (
        db.table(MESSAGES)
        .select("content, metadata, created_at")
        .eq("thread_id", thread_id)
        .eq("role", "session_summary")
        .order("created_at", desc=True)
        .limit(max_sessions)
        .execute()
        .data
    )
    return CaseMemory(
        thread_id=thread_id,
        title=thread["title"],
        text=format_case_memory(thread["title"], list(reversed(rows)), max_chars),
        session_count=len(rows),
    )


def format_case_memory(title: str, sessions: list[dict], max_chars: int) -> str:
    """Render sessions (oldest first), dropping the oldest ones when over budget."""
    header = f"Case: {title}"
    if not sessions:
        return f"{header}\nThis is the first recorded session in this case."

    blocks = []
    for session in sessions:
        meta = session.get("metadata") or {}
        when = _format_date(meta.get("started_at") or session.get("created_at"))
        block = f"Session of {when}:\n{session['content'].strip()}"
        if meta.get("open_questions"):
            block += "\nOpen questions then: " + "; ".join(meta["open_questions"][:5])
        blocks.append(block)

    kept: list[str] = []
    used = len(header)
    for block in reversed(blocks):  # newest first, so the most recent sessions survive the budget
        if kept and used + len(block) + 2 > max_chars:
            break
        kept.append(block[: max_chars - used] if not kept and used + len(block) > max_chars else block)
        used += len(block) + 2
    omitted = len(blocks) - len(kept)
    lines = [header]
    if omitted:
        lines.append(f"[{omitted} earlier session(s) omitted]")
    return "\n\n".join(lines + list(reversed(kept)))


def _format_date(value) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return "an earlier date"

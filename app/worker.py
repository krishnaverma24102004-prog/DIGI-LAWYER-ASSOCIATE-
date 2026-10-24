"""ARQ background worker: `arq app.worker.WorkerSettings` (needs REDIS_URL).

Tasks:
  task_generate_pdf_report(transcript_id, user_id)   PDF report -> Supabase Storage
  task_trigger_n8n_webhook(payload, retry_count=3)   n8n delivery with exponential backoff
  task_batch_embed_documents(document_id, user_id)   chunk + embed a document into the knowledge base
  task_hearing_reminders()                           daily (cron): sync upcoming hearings, remind clients
                                                     on WhatsApp, send each firm's agenda to n8n
  task_purge_expired_trash()                         daily (cron): erase trashed records past 30 days,
                                                     keeping an erasure record per item

Jobs are queued by the API after it has checked the caller's access through RLS. The
worker has no user session, so it uses the service role, and every query is scoped
explicitly to the organization and user recorded in the job; each task re-checks that
the user still belongs to that organization before acting.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from arq import Retry
from arq.cron import cron
from arq.worker import func

from app.core.config import get_settings
from app.database import get_supabase_admin
from app.services import (
    audit_service,
    document_service,
    ecourts_service,
    jurisdiction_service,
    n8n_service,
    pdf_service,
    queue_service,
    rag_service,
    safety_service,
    whatsapp_service,
)
from app.services.audit_service import AuditAction

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

SENIOR_ROLES = {"owner", "partner"}
TRASH_PURGE_HOUR_IST = 2  # 02:00 IST (night, low traffic)
KNOWLEDGE_ROLES = {"owner", "partner", "associate"}


class TaskError(RuntimeError):
    pass


def _role(db, org_id: str, user_id: str) -> str | None:
    rows = (
        db.table("organization_members").select("role").eq("org_id", org_id).eq("user_id", user_id)
        .limit(1).execute().data
    )
    return rows[0]["role"] if rows else None


def report_path(org_id: str, transcript_id: str) -> str:
    """Where a transcript's report is stored; the Storage policy in migration 007 matches this."""
    return f"{org_id}/{transcript_id}.pdf"


def generate_pdf_report(transcript_id: str, user_id: str, db=None) -> dict:
    db = db or get_supabase_admin()
    rows = db.table("transcripts").select("*").eq("id", transcript_id).limit(1).execute().data
    if not rows:
        raise TaskError("Transcript not found")
    transcript = rows[0]
    org_id = transcript["org_id"]
    role = _role(db, org_id, user_id)
    # Same visibility as RLS: your own transcripts, or any in the org for owners and partners.
    if role is None or (transcript["user_id"] != user_id and role not in SENIOR_ROLES):
        raise TaskError("Not allowed to export this transcript")

    document = None
    if transcript.get("document_id"):
        found = (
            db.table("documents").select(document_service.METADATA_COLUMNS)
            .eq("id", transcript["document_id"]).eq("org_id", org_id).limit(1).execute().data
        )
        document = found[0] if found else None

    pdf = pdf_service.build_transcript_report(transcript, document)
    path = report_path(org_id, transcript_id)
    db.storage.from_(get_settings().report_storage_bucket).upload(
        path, pdf, {"content-type": "application/pdf", "upsert": "true"}
    )
    return {"path": path, "filename": pdf_service.report_filename(transcript), "size_bytes": len(pdf)}


def batch_embed_document(document_id: str, user_id: str, title: str | None = None,
                         citation: str | None = None, jurisdiction: str | None = None, db=None) -> dict:
    db = db or get_supabase_admin()
    rows = (
        db.table("documents").select("id, org_id, user_id, filename, extracted_text")
        .eq("id", document_id).limit(1).execute().data
    )
    if not rows:
        raise TaskError("Document not found")
    document = rows[0]
    role = _role(db, document["org_id"], user_id)
    if role not in KNOWLEDGE_ROLES or (document["user_id"] != user_id and role not in SENIOR_ROLES):
        raise TaskError("Not allowed to add this document to the knowledge base")
    result = rag_service.ingest_legal_statutes_and_precedents(
        document["org_id"],
        title or document["filename"],
        document["extracted_text"] or "",
        db=db,
        created_by=user_id,
        metadata={
            "citation": citation,
            "jurisdiction": jurisdiction,
            "jurisdiction_code": jurisdiction_service.normalize(jurisdiction),
            "document_id": document_id,
        },
    )
    return {"source_id": result.source_id, "title": result.title, "chunk_count": result.chunk_count,
            "char_count": result.char_count}


# ----------------------------------------------------------------------------- ARQ tasks


async def task_generate_pdf_report(ctx: dict, transcript_id: str, user_id: str) -> dict:
    from fastapi.concurrency import run_in_threadpool  # ReportLab and Storage calls block

    return await run_in_threadpool(generate_pdf_report, transcript_id, user_id)


async def task_trigger_n8n_webhook(ctx: dict, payload: dict, retry_count: int = 3) -> dict:
    """Deliver a workflow event to n8n; on failure retry after 1x, 2x, 4x... N8N_RETRY_BASE_SECONDS."""
    try:
        return await n8n_service.trigger_post_consultation(payload)
    except Exception as exc:
        attempt = ctx.get("job_try", 1)
        if attempt > retry_count:
            logger.error("n8n delivery failed after %s attempts: %s", attempt, exc)
            raise
        delay = get_settings().n8n_retry_base_seconds * 2 ** (attempt - 1)
        logger.warning("n8n delivery attempt %s failed (%s); retrying in %.0f s", attempt, exc, delay)
        raise Retry(defer=delay) from exc


async def task_batch_embed_documents(ctx: dict, document_id: str, user_id: str, title: str | None = None,
                                     citation: str | None = None, jurisdiction: str | None = None) -> dict:
    from fastapi.concurrency import run_in_threadpool  # embedding is CPU-bound

    return await run_in_threadpool(batch_embed_document, document_id, user_id, title, citation, jurisdiction)


async def send_hearing_reminders(db=None, today: date | None = None) -> dict:
    """Refresh the hearings coming up, remind clients on WhatsApp, and post each firm's agenda to n8n."""
    settings = get_settings()
    db = db or get_supabase_admin()
    today = today or datetime.now(IST).date()
    horizon = (today + timedelta(days=settings.hearing_reminder_days)).isoformat()
    cases = db.table("court_cases").select("*").gte("next_hearing_date", today.isoformat()).lte("next_hearing_date", horizon).execute().data
    stale = datetime.now(timezone.utc) - timedelta(hours=12)
    synced = reminded = 0
    if ecourts_service.is_configured():
        for i, case in enumerate(cases):
            last = case.get("last_synced_at")
            if case.get("cnr") and (not last or datetime.fromisoformat(last) < stale):
                cases[i] = await ecourts_service.sync(db, case)
                synced += 1
    numbers: dict[str, str | None] = {}
    for case in cases:
        if not ecourts_service.needs_reminder(case, today, settings.hearing_reminder_days) or not whatsapp_service.is_configured():
            continue
        if case["org_id"] not in numbers:
            rows = db.table("whatsapp_numbers").select("phone_number_id").eq("org_id", case["org_id"]).eq("enabled", True).limit(1).execute().data
            numbers[case["org_id"]] = rows[0]["phone_number_id"] if rows else None
        number = numbers[case["org_id"]]
        if number is None:
            continue
        hearing = date.fromisoformat(case["next_hearing_date"])
        try:
            await whatsapp_service.send_template(
                number, whatsapp_service.to_wa_id(case["client_phone"]), settings.whatsapp_reminder_template,
                [case["title"], f"{hearing:%d %B %Y}", case.get("court_name") or "the court"],
            )
        except whatsapp_service.WhatsAppError as exc:
            logger.warning("Hearing reminder for case %s failed: %s", case["id"], exc)
            continue
        db.table("court_cases").update({"reminded_for_date": case["next_hearing_date"]}).eq("id", case["id"]).execute()
        reminded += 1
    if n8n_service.is_configured():
        by_org: dict[str, list[dict]] = {}
        for case in cases:
            by_org.setdefault(case["org_id"], []).append(
                {k: case.get(k) for k in ("id", "title", "court_name", "case_number", "next_hearing_date", "user_id", "cnr")}
            )
        for org_id, items in by_org.items():
            try:
                await n8n_service.trigger_workflow("hearings-agenda", {"event": "hearings.upcoming", "org_id": org_id,
                                                                     "date": today.isoformat(), "hearings": items})
            except Exception as exc:
                logger.warning("Hearing agenda for org %s not delivered: %s", org_id, exc)
    return {"hearings": len(cases), "synced": synced, "reminded": reminded}


async def task_hearing_reminders(ctx: dict) -> dict:
    return await send_hearing_reminders()


def purge_expired_trash(db=None) -> dict:
    """Erase the snapshots of records trashed more than 30 days ago; each erasure is audited."""
    rows = safety_service.purge_expired(db or get_supabase_admin())
    for row in rows:
        audit_service.log_action(None, row["org_id"], AuditAction.PURGE_EXPIRED_TRASH, row["kind"], row["item_id"],
                   metadata={"trash_id": row["id"], "title": row.get("title"), "sha256": row["snapshot_sha256"]})
    return {"purged": len(rows)}


async def task_purge_expired_trash(ctx: dict) -> dict:
    from fastapi.concurrency import run_in_threadpool

    return await run_in_threadpool(purge_expired_trash)


def _utc_time(ist_hour: int) -> tuple[int, int]:
    minutes = (ist_hour * 60 - 330) % (24 * 60)  # IST is UTC+5:30
    return minutes // 60, minutes % 60


async def startup(ctx: dict) -> None:
    logging.basicConfig(level=logging.INFO)
    from app.services import anthropic_service

    if problems := anthropic_service.production_model_problems():
        raise RuntimeError("Refusing to start in production with a test model: " + "; ".join(problems))
    if get_settings().rag_enabled:
        from fastapi.concurrency import run_in_threadpool

        await run_in_threadpool(rag_service.get_embedder().warm_up)


class WorkerSettings:
    functions = [
        func(task_generate_pdf_report, timeout=300),
        # max_tries bounds retry_count: up to 10 deliveries.
        func(task_trigger_n8n_webhook, timeout=60, max_tries=10),
        func(task_batch_embed_documents, timeout=1800),
    ]
    cron_jobs = [
        cron(task_hearing_reminders, hour=_utc_time(get_settings().hearing_reminder_hour_ist)[0],
             minute=_utc_time(get_settings().hearing_reminder_hour_ist)[1], run_at_startup=False, timeout=900),
        cron(task_purge_expired_trash, hour=_utc_time(TRASH_PURGE_HOUR_IST)[0], minute=_utc_time(TRASH_PURGE_HOUR_IST)[1],
             run_at_startup=False, timeout=600),
    ]
    queue_name = queue_service.QUEUE_NAME
    on_startup = startup
    keep_result = 3600  # job results (report paths) are readable for an hour
    max_jobs = 4
    redis_settings = queue_service.redis_settings() if queue_service.is_configured() else None

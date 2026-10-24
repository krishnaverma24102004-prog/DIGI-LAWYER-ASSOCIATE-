"""Background job status: `GET /api/v1/jobs/{job_id}` for jobs the caller queued."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.dependencies.org import OrgContext, get_org_context
from app.services import queue_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

SIGNED_URL_SECONDS = 300


def _signed_report_url(ctx: OrgContext, path: str) -> str | None:
    """A short-lived download link, created as the user: Storage RLS checks they may see it."""
    signed = ctx.db().storage.from_(get_settings().report_storage_bucket).create_signed_url(path, SIGNED_URL_SECONDS)
    return signed.get("signedURL") or signed.get("signedUrl")


@router.get("/{job_id}")
async def get_job(job_id: str, ctx: OrgContext = Depends(get_org_context)):
    if not queue_service.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Background jobs are not configured (REDIS_URL)")
    job = await queue_service.get_job(job_id, ctx.user.id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    body = {"job_id": job.job_id, "function": job.function, "status": job.status, "error": job.error}
    if job.status == "complete":
        body["result"] = job.result
        if job.function == "task_generate_pdf_report":
            try:
                body["download_url"] = await run_in_threadpool(_signed_report_url, ctx, job.result["path"])
            except Exception:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not available") from None
            body["expires_in"] = SIGNED_URL_SECONDS
    return body

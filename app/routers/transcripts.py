"""Consultation transcripts in the caller's active organization.

RLS shows owners and partners every transcript in the org, and associates and
paralegals only their own. Viewing, exporting and deleting are audit-logged.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from app.dependencies.org import OrgContext, get_org_context
from app.routers.safety import ReasonQuery, delete_response
from app.models.transcript import Transcript, TranscriptCreate, TranscriptUpdate
from app.services import audit_service, document_service, pdf_service, queue_service, transcript_service
from app.services.audit_service import AuditAction

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def _get_or_404(ctx: OrgContext, transcript_id: UUID) -> dict:
    row = transcript_service.get_transcript(ctx.db(), str(transcript_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transcript not found")
    return row


def _audit(ctx: OrgContext, request: Request, action: AuditAction, transcript_id, **metadata) -> None:
    try:
        audit_service.log_action(
            ctx.user.id,
            ctx.org_id,
            action,
            "transcript",
            str(transcript_id),
            ip_address=audit_service.client_ip(request),
            metadata=metadata or None,
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("", response_model=list[Transcript])
def list_transcripts(ctx: OrgContext = Depends(get_org_context)):
    return transcript_service.list_transcripts(ctx.db())


@router.post("", response_model=Transcript, status_code=status.HTTP_201_CREATED)
def create_transcript(payload: TranscriptCreate, ctx: OrgContext = Depends(get_org_context)):
    return transcript_service.create_transcript(ctx.db(), ctx.user.id, payload)


@router.get("/{transcript_id}", response_model=Transcript)
def get_transcript(transcript_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    row = _get_or_404(ctx, transcript_id)
    _audit(ctx, request, AuditAction.VIEW_TRANSCRIPT, transcript_id)
    return row


@router.patch("/{transcript_id}", response_model=Transcript)
def update_transcript(transcript_id: UUID, payload: TranscriptUpdate, ctx: OrgContext = Depends(get_org_context)):
    row = transcript_service.update_transcript(ctx.db(), str(transcript_id), payload)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transcript not found")
    return row


@router.delete("/{transcript_id}")
async def delete_transcript(transcript_id: UUID, request: Request, reason: ReasonQuery = None, ctx: OrgContext = Depends(get_org_context)):
    """Move to the trash (restorable for 30 days), or ask a partner or owner to (202) when your role can't."""
    row = await run_in_threadpool(_get_or_404, ctx, transcript_id)
    return await delete_response(ctx, request, "transcript", transcript_id, label=row.get("title") or "Consultation", reason=reason)


@router.get(
    "/{transcript_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "Consultation summary report"}},
)
def download_transcript_pdf(transcript_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Download the consultation report as a PDF. RLS limits this to transcripts the caller may see."""
    row = _get_or_404(ctx, transcript_id)

    document = None
    if row.get("document_id"):
        document = document_service.get_document(ctx.user.access_token, row["document_id"], org_id=ctx.org_id)

    pdf = pdf_service.build_transcript_report(row, document)
    _audit(ctx, request, AuditAction.EXPORT_PDF_REPORT, transcript_id, filename=pdf_service.report_filename(row))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf_service.report_filename(row)}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/{transcript_id}/pdf/jobs", status_code=status.HTTP_202_ACCEPTED)
async def queue_transcript_pdf(transcript_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Generate the PDF report in the background; poll `GET /jobs/{job_id}` for a download link."""
    if not queue_service.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Background jobs are not configured; use GET .../pdf")
    await run_in_threadpool(_get_or_404, ctx, transcript_id)  # RLS: only transcripts the caller may see
    job_id = await queue_service.enqueue("task_generate_pdf_report", transcript_id=str(transcript_id), user_id=ctx.user.id)
    await run_in_threadpool(_audit, ctx, request, AuditAction.QUEUE_PDF_REPORT, transcript_id, job_id=job_id)
    return {"job_id": job_id, "status": "queued"}

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, StringConstraints

from app.core.rate_limiter import limit
from app.core.rbac import Permission
from app.dependencies.org import OrgContext, get_org_context, require_permission
from app.routers.safety import ReasonQuery, delete_response
from app.models.document import Document, DocumentUploadResponse
from app.services import audit_service, contract_diff_service, document_service, governing_law, jurisdiction_service
from app.services.audit_service import AuditAction

router = APIRouter(prefix="/documents", tags=["documents"])

PREVIEW_CHARS = 500


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(limit("llm"))])
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(require_permission(Permission.DOCUMENTS_UPLOAD)),
):
    """Upload a contract or case document (PDF, scanned PDF, image or .txt) into the active organization.

    Scanned pages and images are OCR'd; pages OCR can't read are transcribed by Claude vision.
    """
    data = await file.read(document_service.MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")
    if len(data) > document_service.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Files are limited to {document_service.MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    filename = document_service.clean_filename(file.filename)
    try:
        extracted = await run_in_threadpool(document_service.extract_text, filename, file.content_type or "", data)
    except document_service.DocumentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    row = {
        "user_id": ctx.user.id,
        "org_id": ctx.org_id,
        "filename": filename,
        "content_type": extracted.content_type,
        "size_bytes": len(data),
        "page_count": extracted.page_count,
        "char_count": len(extracted.text),
        "extracted_text": extracted.text,
        "extraction": extracted.extraction,
        "governing_law": governing_law.detect(extracted.text),
    }
    saved = await run_in_threadpool(document_service.save_document, ctx.user.access_token, row, ctx.org_id)
    saved.pop("extracted_text", None)
    try:
        await audit_service.alog_action(
            ctx.user.id,
            ctx.org_id,
            AuditAction.UPLOAD_CONTRACT,
            "document",
            saved["id"],
            ip_address=audit_service.client_ip(request),
            metadata={"filename": filename, "size_bytes": len(data), "extraction": extracted.extraction},
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {**saved, "preview": extracted.text[:PREVIEW_CHARS]}


class CompareRequest(BaseModel):
    original_document_id: UUID
    revised_document_id: UUID
    jurisdiction: str | None = None
    our_side: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    analyze: bool = True


@router.post("/compare", dependencies=[Depends(limit("llm"))])
async def compare_documents(payload: CompareRequest, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Clause-by-clause redline of two versions of a contract, with Claude's risk analysis.

    Typical use: the original draft vs. opposing counsel's revision. Returns every clause
    (unchanged / renumbered / modified / added / deleted) with an inline diff, plus
    `additions`, `deletions`, `modifications`, `risk_delta` (Increased / Decreased / Neutral)
    and `recommended_counter_clauses`.
    """
    if payload.original_document_id == payload.revised_document_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose two different documents")
    try:
        profile = jurisdiction_service.require_profile(payload.jurisdiction)
    except jurisdiction_service.UnknownJurisdiction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    docs = []
    for doc_id in (payload.original_document_id, payload.revised_document_id):
        row = await run_in_threadpool(
            document_service.get_document, ctx.user.access_token, str(doc_id), include_text=True, org_id=ctx.org_id
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Document {doc_id} not found")
        docs.append(row)

    report = await contract_diff_service.compare(
        docs[0]["extracted_text"], docs[1]["extracted_text"], analyze=payload.analyze, jurisdiction=profile, our_side=payload.our_side
    )
    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, AuditAction.COMPARE_DOCUMENTS, "document", docs[1]["id"],
            ip_address=audit_service.client_ip(request),
            metadata={"original": docs[0]["id"], "revised": docs[1]["id"], "risk_delta": report["risk_delta"]},
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    # The contract's own law vs the one analysed: conclusions about enforceability carry a caveat.
    laws = {
        side: governing_law.assess(doc.get("governing_law") or governing_law.detect(doc["extracted_text"]), profile)
        for side, doc in (("original", docs[0]), ("revised", docs[1]))
    }
    caveat = next((law["caveat"] for law in (laws["revised"], laws["original"]) if law["caveat"]), None)
    if caveat:
        for clause in report["clauses"]:
            analysis = clause.get("analysis") or {}
            if governing_law.concerns_enforceability(f"{analysis.get('explanation', '')} {analysis.get('change_summary', '')}"):
                clause["jurisdiction_caveat"] = caveat
    return {
        "original": {"id": docs[0]["id"], "filename": docs[0]["filename"]},
        "revised": {"id": docs[1]["id"], "filename": docs[1]["filename"]},
        **report,
        "governing_law": laws,
        "jurisdiction_caveat": caveat,
    }


@router.get("", response_model=list[Document])
async def list_documents(ctx: OrgContext = Depends(get_org_context)):
    return await run_in_threadpool(document_service.list_documents, ctx.user.access_token, ctx.org_id)


@router.delete("/{document_id}")
async def delete_document(document_id: UUID, request: Request, reason: ReasonQuery = None, ctx: OrgContext = Depends(get_org_context)):
    """Move to the trash (restorable for 30 days), or ask a partner or owner to (202) when your role can't."""
    row = await run_in_threadpool(document_service.get_document, ctx.user.access_token, str(document_id), org_id=ctx.org_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return await delete_response(ctx, request, "document", document_id, label=row.get("filename"), reason=reason)


@router.get("/{document_id}", response_model=Document)
async def get_document(document_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    row = await run_in_threadpool(
        document_service.get_document, ctx.user.access_token, str(document_id), org_id=ctx.org_id
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return row

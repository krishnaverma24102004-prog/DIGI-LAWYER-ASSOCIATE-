"""The organization's legal knowledge base (RAG): statutes, case law, firm precedents."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints

from app.core.rbac import Permission
from app.dependencies.org import OrgContext, get_org_context, require_permission
from app.routers.safety import ReasonQuery, delete_response
from app.core.rate_limiter import limit
from app.services import audit_service, document_service, jurisdiction_service, queue_service, rag_service
from app.services.audit_service import AuditAction

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeSearch(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=5000)]
    top_k: int = Field(default=5, ge=1, le=20)
    match_threshold: float | None = Field(default=None, ge=0, le=1)
    jurisdiction: str | None = Field(default=None, description="IN, US, US-<state> or UK")


@router.post("/upload", status_code=status.HTTP_201_CREATED, dependencies=[Depends(limit("llm"))])
async def upload_knowledge(
    request: Request,
    title: Annotated[str, Form(min_length=1, max_length=300)],
    content: Annotated[str | None, Form(description="The text; or send `file` instead")] = None,
    file: Annotated[UploadFile | None, File(description="A PDF or .txt file instead of `content`")] = None,
    citation: Annotated[str | None, Form(max_length=300, description="e.g. 'Housing Act 1988, s.21'")] = None,
    jurisdiction: Annotated[str | None, Form(max_length=100)] = None,
    source_url: Annotated[str | None, Form(max_length=2000)] = None,
    ctx: OrgContext = Depends(require_permission(Permission.KNOWLEDGE_UPLOAD)),
):
    """Add a statute, case or firm precedent. It is chunked, embedded and made searchable."""
    if file is not None and content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Send either `content` or `file`, not both")
    if file is not None:
        data = await file.read(document_service.MAX_UPLOAD_BYTES + 1)
        if len(data) > document_service.MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File is too large")
        try:
            extracted = await run_in_threadpool(
                document_service.extract_text, document_service.clean_filename(file.filename), file.content_type or "", data
            )
        except document_service.DocumentError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        text = extracted.text
    elif content and content.strip():
        text = content
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide `content` or a `file`")

    try:
        result = await rag_service.aingest_legal_statutes_and_precedents(
            ctx.org_id,
            title,
            text,
            db=ctx.db(),
            created_by=ctx.user.id,
            metadata={
                "citation": citation,
                "jurisdiction": jurisdiction,
                # Normalized tag used by jurisdiction filtering (IN, US, US-CA, UK).
                "jurisdiction_code": jurisdiction_service.normalize(jurisdiction),
                "source_url": source_url,
            },
        )
    except rag_service.RagError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, AuditAction.UPLOAD_KNOWLEDGE, "knowledge_source", result.source_id,
            ip_address=audit_service.client_ip(request), metadata={"title": result.title, "chunks": result.chunk_count},
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {
        "source_id": result.source_id,
        "title": result.title,
        "chunk_count": result.chunk_count,
        "char_count": result.char_count,
    }


class FromDocument(BaseModel):
    document_id: UUID
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] | None = None
    citation: str | None = Field(default=None, max_length=300)
    jurisdiction: str | None = Field(default=None, max_length=100)


@router.post("/from-document", status_code=status.HTTP_202_ACCEPTED)
async def add_document_to_knowledge(
    payload: FromDocument, request: Request, ctx: OrgContext = Depends(require_permission(Permission.KNOWLEDGE_UPLOAD))
):
    """Index an uploaded document (e.g. a long statute PDF) in the knowledge base, in the background.

    Poll `GET /jobs/{job_id}`. Without background jobs (no REDIS_URL) it is indexed right away.
    """
    # RLS: the caller must be able to see the document.
    document = await run_in_threadpool(
        document_service.get_document, ctx.user.access_token, str(payload.document_id), org_id=ctx.org_id
    )
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if queue_service.is_configured():
        job_id = await queue_service.enqueue(
            "task_batch_embed_documents", document_id=str(payload.document_id), user_id=ctx.user.id,
            title=payload.title, citation=payload.citation, jurisdiction=payload.jurisdiction,
        )
        resource_id, response = str(payload.document_id), {"job_id": job_id, "status": "queued"}
    else:
        full = await run_in_threadpool(
            document_service.get_document, ctx.user.access_token, str(payload.document_id), include_text=True, org_id=ctx.org_id
        )
        try:
            result = await rag_service.aingest_legal_statutes_and_precedents(
                ctx.org_id, payload.title or full["filename"], full.get("extracted_text") or "", db=ctx.db(),
                created_by=ctx.user.id,
                metadata={"citation": payload.citation, "jurisdiction": payload.jurisdiction,
                          "jurisdiction_code": jurisdiction_service.normalize(payload.jurisdiction),
                          "document_id": str(payload.document_id)},
            )
        except rag_service.RagError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        resource_id = result.source_id
        response = {"status": "complete", "result": {"source_id": result.source_id, "title": result.title,
                                                      "chunk_count": result.chunk_count, "char_count": result.char_count}}
    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, AuditAction.UPLOAD_KNOWLEDGE, "knowledge_source", resource_id,
            ip_address=audit_service.client_ip(request), metadata={"document_id": str(payload.document_id), **response},
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return response


@router.get("")
async def list_knowledge(ctx: OrgContext = Depends(require_permission(Permission.KNOWLEDGE_VIEW))):
    """One entry per uploaded source."""
    return await run_in_threadpool(rag_service.list_sources, ctx.db())


@router.post("/search")
async def search_knowledge(
    payload: KnowledgeSearch, ctx: OrgContext = Depends(require_permission(Permission.KNOWLEDGE_VIEW))
):
    """Semantic search, the same retrieval live consultations use."""
    try:
        profile = jurisdiction_service.require_profile(payload.jurisdiction)
    except jurisdiction_service.UnknownJurisdiction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    precedents = await rag_service.aretrieve_relevant_precedents(
        ctx.org_id, payload.query, payload.top_k, db=ctx.db(), match_threshold=payload.match_threshold,
        jurisdictions=profile.rag_codes if profile else None,
    )
    return [p.citation() for p in precedents]


@router.delete("/{source_id}")
async def delete_knowledge(source_id: UUID, request: Request, reason: ReasonQuery = None, ctx: OrgContext = Depends(get_org_context)):
    """Move to the trash (restorable for 30 days), or ask a partner or owner to (202) when your role can't."""
    rows = await run_in_threadpool(
        lambda: ctx.db().table(rag_service.TABLE).select("title").eq("source_id", str(source_id)).eq("chunk_index", 0).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return await delete_response(ctx, request, "knowledge_source", source_id, label=rows[0]["title"], reason=reason)

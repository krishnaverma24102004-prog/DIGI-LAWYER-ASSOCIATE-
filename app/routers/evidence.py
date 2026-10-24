"""Evidence analysis: witness contradictions and deposition transcription."""

from pathlib import PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.core.rate_limiter import limit
from app.dependencies.org import OrgContext, get_org_context
from app.services import (
    audit_service,
    document_service,
    evidence_service,
    jurisdiction_service,
    memory_service,
    transcript_service,
)
from app.services.audit_service import AuditAction
from app.services.evidence_service import EvidenceSource

router = APIRouter(prefix="/evidence", tags=["evidence"])

MAX_AUDIO_BYTES = 50 * 1024 * 1024


class StatementInput(BaseModel):
    """Exactly one of: text, a saved transcript, or an uploaded document."""

    text: Annotated[str, StringConstraints(max_length=evidence_service.MAX_STATEMENT_CHARS)] | None = None
    transcript_id: UUID | None = None
    document_id: UUID | None = None
    label: Annotated[str, StringConstraints(max_length=200)] | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if sum(x is not None and x != "" for x in (self.text, self.transcript_id, self.document_id)) != 1:
            raise ValueError("Give exactly one of text, transcript_id or document_id")
        return self


class ContradictionRequest(BaseModel):
    statement: StatementInput
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)
    transcript_ids: list[UUID] = Field(default_factory=list, max_length=10)
    thread_id: UUID | None = Field(default=None, description="Include this case thread's memory as a source")
    jurisdiction: str | None = None


async def _document(ctx: OrgContext, doc_id: UUID) -> dict:
    row = await run_in_threadpool(document_service.get_document, ctx.user.access_token, str(doc_id), include_text=True, org_id=ctx.org_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Document {doc_id} not found")
    return row


async def _transcript(ctx: OrgContext, transcript_id: UUID) -> dict:
    row = await run_in_threadpool(transcript_service.get_transcript, ctx.db(), str(transcript_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Transcript {transcript_id} not found")
    return row


@router.post("/analyze-contradictions", dependencies=[Depends(limit("llm"))])
async def analyze_contradictions(payload: ContradictionRequest, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Cross-reference a witness statement against the case's evidence.

    Returns contradictions (each with the statement line and timestamp, the conflicting source
    quote, a severity score and cross-examination questions), consistent points, and how many
    model findings were discarded because their quotes could not be verified.
    """
    try:
        profile = jurisdiction_service.require_profile(payload.jurisdiction)
    except jurisdiction_service.UnknownJurisdiction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    s = payload.statement
    try:
        if s.text:
            statement = evidence_service.parse_statement_text(s.text, s.label or "Witness statement")
            statement.origin = {"type": "text"}
        elif s.transcript_id:
            statement = evidence_service.statement_from_transcript(await _transcript(ctx, s.transcript_id))
        else:
            doc = await _document(ctx, s.document_id)
            statement = evidence_service.parse_statement_text(doc["extracted_text"], s.label or doc["filename"])
            statement.origin = {"type": "document", "id": doc["id"]}
    except evidence_service.EvidenceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if s.label:
        statement.label = s.label

    sources: list[EvidenceSource] = []
    for doc_id in payload.document_ids:
        if doc_id == s.document_id:
            continue
        doc = await _document(ctx, doc_id)
        sources.append(EvidenceSource(f"S{len(sources) + 1}", "document", doc["filename"], doc["extracted_text"], doc["id"]))
    for transcript_id in payload.transcript_ids:
        if transcript_id == s.transcript_id:
            continue
        row = await _transcript(ctx, transcript_id)
        sources.append(EvidenceSource(f"S{len(sources) + 1}", "transcript", row.get("title") or "Transcript", row.get("content") or "", row["id"]))
    if payload.thread_id:
        memory = await run_in_threadpool(memory_service.load_case_memory, ctx.db(), str(payload.thread_id))
        if memory is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Case thread not found")
        sources.append(EvidenceSource(f"S{len(sources) + 1}", "case_memory", f"Case notes: {memory.title}", memory.text, memory.thread_id))

    try:
        report = await evidence_service.analyze(statement, sources, jurisdiction=profile)
    except evidence_service.EvidenceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, AuditAction.ANALYZE_CONTRADICTIONS, "evidence", statement.origin.get("id"),
            ip_address=audit_service.client_ip(request),
            metadata={"sources": [src["ref_id"] for src in report["sources"]], "contradictions": len(report["contradictions"])},
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return report


@router.post("/transcribe", dependencies=[Depends(limit("llm"))])
async def transcribe(
    request: Request,
    file: UploadFile = File(..., description="Deposition or interview recording (mp3, wav, m4a, ...)"),
    # An opt-out flag: browsers and this FastAPI version send an absent checkbox as false.
    ephemeral: Annotated[bool, Form(description="Don't keep the transcript as a document")] = False,
    ctx: OrgContext = Depends(get_org_context),
):
    """Transcribe a recording into timestamped, speaker-labelled lines, ready to analyze.

    Unless `ephemeral` is set, the transcript is stored as a document so it can be used as a
    statement or a source later.
    """
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    if not audio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Recordings are limited to 50 MB")
    try:
        result = await evidence_service.transcribe_recording(audio)
    except evidence_service.EvidenceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if not result["text"].strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No speech was recognised in the recording")

    document_id = None
    if not ephemeral:
        name = PurePath(document_service.clean_filename(file.filename)).stem
        row = {
            "user_id": ctx.user.id,
            "org_id": ctx.org_id,
            "filename": f"{name} (transcript).txt",
            "content_type": "text/plain",
            "size_bytes": len(result["text"].encode()),
            "page_count": None,
            "char_count": len(result["text"]),
            "extracted_text": result["text"],
            "extraction": {"methods": {"audio_transcription": 1}, "duration_seconds": result["duration"]},
        }
        saved = await run_in_threadpool(document_service.save_document, ctx.user.access_token, row, ctx.org_id)
        document_id = saved["id"]
    try:
        await audit_service.alog_action(
            ctx.user.id, ctx.org_id, AuditAction.TRANSCRIBE_EVIDENCE, "document", document_id,
            ip_address=audit_service.client_ip(request), metadata={"duration_seconds": result["duration"]},
        )
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {**result, "document_id": document_id}

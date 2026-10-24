"""Legal drafting: generate notices and pleadings from case context, edit, revise, export."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints

from app.core.guardrails import PiiMasker, mask_pii
from app.core.rate_limiter import limit
from app.dependencies.org import OrgContext, get_org_context
from app.routers.safety import ReasonQuery, delete_response
from app.services import (
    anthropic_service,
    audit_service,
    citation_service,
    contract_diff_service,
    document_service,
    draft_check,
    drafting_engine,
    jurisdiction_service,
    memory_service,
)
from app.services.audit_service import AuditAction

router = APIRouter(prefix="/drafting", tags=["drafting"])

TABLE = "drafts"
COLUMNS = ("id, org_id, user_id, thread_id, doc_type, jurisdiction, title, content, variables, missing, status, "
           "approved_by, approved_at, fact_basis, created_at, updated_at")
MAX_DOC_CONTEXT_CHARS = 30_000
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
Text = Annotated[str, StringConstraints(max_length=20_000)]


class GenerateRequest(BaseModel):
    doc_type: Literal["legal_notice", "bail_application", "cease_and_desist", "nda", "affidavit"]
    jurisdiction: str | None = None
    thread_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list, max_length=5)
    facts: Text | None = Field(default=None, description="Extra facts from the lawyer")
    instructions: Text | None = None
    variables: dict[str, Annotated[str, StringConstraints(max_length=1000)]] = Field(default_factory=dict)


class SectionModel(BaseModel):
    heading: Annotated[str, StringConstraints(max_length=500)] | None = None
    paragraphs: list[Text] = Field(max_length=200)


class ContentModel(BaseModel):
    sections: list[SectionModel] = Field(max_length=100)
    signature_block: list[Annotated[str, StringConstraints(max_length=500)]] = Field(default_factory=list, max_length=20)


class DraftUpdate(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] | None = None
    content: ContentModel | None = None
    status: Literal["draft", "final"] | None = None


class DraftCreate(BaseModel):
    """A draft written or assembled by the lawyer (e.g. a negotiated contract from the redline view)."""

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    doc_type: Annotated[str, StringConstraints(pattern=r"^[a-z_]{2,40}$")] = "contract"
    jurisdiction: str | None = None
    thread_id: UUID | None = None
    content: ContentModel


class ReviseRequest(BaseModel):
    text: Text = Field(min_length=1)
    instruction: Annotated[str, StringConstraints(min_length=3, max_length=2000)]
    jurisdiction: str | None = None
    context: Text | None = Field(default=None, description="Surrounding clauses, for consistency")


def _profile(code: str | None):
    try:
        return jurisdiction_service.require_profile(code)
    except jurisdiction_service.UnknownJurisdiction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


async def _audit(ctx: OrgContext, request: Request, action: AuditAction, draft_id: str, **meta) -> None:
    try:
        await audit_service.alog_action(ctx.user.id, ctx.org_id, action, "draft", draft_id,
                                        ip_address=audit_service.client_ip(request), metadata=meta or None)
    except audit_service.AuditError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _case_context(ctx: OrgContext, payload: GenerateRequest) -> tuple[str, list[str]]:
    """Everything the drafter may draw on, as tagged blocks, and the case's key facts. Blocking (database reads)."""
    blocks, case_facts = [], []
    if payload.thread_id:
        db = ctx.db()
        memory = memory_service.load_case_memory(db, str(payload.thread_id))
        if memory is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Case thread not found")
        blocks.append(f"<case_history>\n{memory.text}\n</case_history>")
        sessions = (
            db.table("transcripts").select("title, summary, metadata, created_at")
            .eq("thread_id", str(payload.thread_id)).order("created_at", desc=True).limit(3).execute().data
        )
        for s in sessions:
            facts = [f.get("fact") for f in ((s.get("metadata") or {}).get("analysis") or {}).get("key_facts", []) if f.get("fact")]
            body = (s.get("summary") or "").strip()
            if facts:
                body += "\nKey facts: " + "; ".join(facts)
                case_facts += facts
            if body:
                blocks.append(f'<consultation title="{(s.get("title") or "").replace(chr(34), chr(39))}">\n{body}\n</consultation>')
    for doc_id in payload.document_ids:
        row = document_service.get_document(ctx.user.access_token, str(doc_id), include_text=True, org_id=ctx.org_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Document {doc_id} not found")
        excerpt = document_service.DocumentContext(row["id"], row["filename"], row["extracted_text"]).prompt_text(
            f"{payload.facts or ''} {payload.instructions or ''} {payload.doc_type}", MAX_DOC_CONTEXT_CHARS
        )
        blocks.append(f'<document filename="{row["filename"].replace(chr(34), chr(39))}">\n{excerpt}\n</document>')
    if payload.facts:
        blocks.append(f"<lawyer_notes>\n{payload.facts}\n</lawyer_notes>")
    return "\n\n".join(blocks) or "(No case context was provided.)", case_facts


@router.get("/types")
def list_types():
    """Document types and their templates per jurisdiction family (IN, US, UK, * = any)."""
    return [
        {"doc_type": t.doc_type, "label": drafting_engine.DOC_TYPES[t.doc_type], "family": t.family, "name": t.name,
         "variables": t.variables, "slots": t.slots}
        for t in drafting_engine.TEMPLATES
    ]


@router.post("/generate", status_code=status.HTTP_201_CREATED, dependencies=[Depends(limit("llm"))])
async def generate(payload: GenerateRequest, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Draft a legal notice, bail application, cease and desist letter, NDA or affidavit.

    Facts come from the case thread (memory and recent sessions), attached documents and the
    lawyer's notes; values the lawyer gives in `variables` always win. The draft is saved and
    returned with `missing` information still to supply.
    """
    profile = _profile(payload.jurisdiction)
    try:
        template = drafting_engine.get_template(payload.doc_type, profile)
    except drafting_engine.DraftingError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    user_values = {k: v for k, v in payload.variables.items() if k in template.variables and v.strip()}
    context, case_facts = await run_in_threadpool(_case_context, ctx, payload)

    fill = None
    masker = PiiMasker()
    if anthropic_service.is_configured():
        masked_provided = {k: mask_pii(v, masker).text for k, v in user_values.items()}
        try:
            fill = await anthropic_service.fill_draft(
                drafting_engine.template_spec(template, masked_provided),
                await run_in_threadpool(lambda: mask_pii(context, masker).text),
                jurisdiction=profile,
                instructions=mask_pii(payload.instructions, masker).text if payload.instructions else None,
            )
        except anthropic_service.AIServiceError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Drafting failed: {exc}") from exc

    variables = drafting_engine.automatic_variables(profile)
    # What the draft may rely on without checking: the self-check flags anything else (draft_check.py).
    fact_basis = {
        "variables": {**variables, **user_values}, "provided": user_values, "notes": payload.facts or "",
        "case_facts": case_facts, "document_ids": [str(d) for d in payload.document_ids],
    }
    slots: dict[str, str] = {}
    if fill is not None:
        variables.update({v.name: masker.unmask(v.value) for v in fill.variables if v.name in template.variables})
        slots = {s.name: masker.unmask(s.value) for s in fill.slots if s.name in template.slots}
    variables.update(user_values)

    rendered = drafting_engine.render(template, variables, slots)
    # The template's unfilled fields plus what Claude says is missing, without repeats.
    missing: list[str] = []
    for item in rendered["missing"] + ([masker.unmask(m) for m in fill.missing_information] if fill else []):
        if item.strip().lower().rstrip(".") not in {m.lower().rstrip(".") for m in missing}:
            missing.append(item.strip())
    row = {
        "org_id": ctx.org_id,
        "user_id": ctx.user.id,
        "thread_id": str(payload.thread_id) if payload.thread_id else None,
        "doc_type": payload.doc_type,
        "jurisdiction": profile.code if profile else None,
        "title": (masker.unmask(fill.title) if fill and fill.title else rendered["title"])[:300],
        "content": {"sections": rendered["sections"], "signature_block": rendered["signature_block"]},
        "variables": variables,
        "missing": missing,
        "fact_basis": fact_basis,
    }
    saved = await run_in_threadpool(lambda: ctx.db().table(TABLE).insert(row).execute().data[0])
    await _audit(ctx, request, AuditAction.GENERATE_DRAFT, saved["id"], doc_type=payload.doc_type, thread_id=row["thread_id"])
    return {**saved, "template": template.name, "ai_filled": fill is not None}


@router.post("/revise-clause", dependencies=[Depends(limit("llm"))])
async def revise_clause(payload: ReviseRequest, ctx: OrgContext = Depends(get_org_context)):
    """Rewrite one clause as instructed; returns the revision and an inline diff."""
    if not anthropic_service.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI revision needs ANTHROPIC_API_KEY")
    masker = PiiMasker()
    try:
        revision = await anthropic_service.revise_clause(
            mask_pii(payload.text, masker).text,
            mask_pii(payload.instruction, masker).text,
            jurisdiction=_profile(payload.jurisdiction),
            context=mask_pii(payload.context, masker).text if payload.context else None,
        )
    except anthropic_service.AIServiceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Revision failed: {exc}") from exc
    revised = masker.unmask(revision.revised_text)
    return {
        "revised_text": revised,
        "explanation": masker.unmask(revision.explanation),
        "inline_diff": contract_diff_service.inline_diff(payload.text, revised),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_draft(payload: DraftCreate, request: Request, ctx: OrgContext = Depends(get_org_context)):
    profile = _profile(payload.jurisdiction)
    content = payload.content.model_dump()
    text = "\n".join([p for s in payload.content.sections for p in [s.heading or "", *s.paragraphs]])
    row = {
        "org_id": ctx.org_id,
        "user_id": ctx.user.id,
        "thread_id": str(payload.thread_id) if payload.thread_id else None,
        "doc_type": payload.doc_type,
        "jurisdiction": profile.code if profile else None,
        "title": payload.title,
        "content": content,
        "variables": {},
        "missing": sorted({m.group(0)[2:-2] for m in drafting_engine.PLACEHOLDER.finditer(text)}),
    }
    saved = await run_in_threadpool(lambda: ctx.db().table(TABLE).insert(row).execute().data[0])
    await _audit(ctx, request, AuditAction.GENERATE_DRAFT, saved["id"], doc_type=payload.doc_type, source="manual")
    return saved


@router.get("")
def list_drafts(ctx: OrgContext = Depends(get_org_context), thread_id: UUID | None = Query(None)):
    query = ctx.db().table(TABLE).select("id, thread_id, doc_type, jurisdiction, title, status, created_at, updated_at")
    if thread_id:
        query = query.eq("thread_id", str(thread_id))
    return query.order("updated_at", desc=True).limit(100).execute().data


def _get(ctx: OrgContext, draft_id: UUID) -> dict:
    rows = ctx.db().table(TABLE).select(COLUMNS).eq("id", str(draft_id)).limit(1).execute().data
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    return rows[0]


@router.get("/{draft_id}")
def get_draft(draft_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    return _get(ctx, draft_id)


async def _draft_sources(ctx: OrgContext, draft: dict) -> tuple[citation_service.Sources, list[str]]:
    """What the draft's citations and facts are checked against: its fact basis, its documents, and the case-law index."""
    basis = draft.get("fact_basis") or {}
    documents = []
    for doc_id in basis.get("document_ids") or []:
        row = await run_in_threadpool(document_service.get_document, ctx.user.access_token, doc_id, include_text=True, org_id=ctx.org_id)
        if row:
            documents.append(row["extracted_text"])
    basis_text = draft_check.basis_text(basis, documents)
    sources = citation_service.Sources.from_texts(basis_text)
    keys, names = citation_service.case_lookups(draft_check.draft_text(draft))
    if keys or names:
        try:
            known = await run_in_threadpool(citation_service.lookup_authorities, ctx.db(), keys, names)
            sources = sources.with_known(*known)
        except Exception:  # the index is a help, not a requirement: unknown cases stay unverified
            pass
    return sources, documents


@router.get("/{draft_id}/checklist")
async def draft_checklist(draft_id: UUID, ctx: OrgContext = Depends(get_org_context)):
    """Before export or approval: unverified citations, values not in the confirmed facts, blanks to fill."""
    draft = await run_in_threadpool(_get, ctx, draft_id)
    sources, documents = await _draft_sources(ctx, draft)
    return draft_check.checklist(draft, sources, documents)


@router.post("/{draft_id}/approve")
async def approve_draft(draft_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    """Mark the draft reviewed: records who approved it and when, and removes the "unreviewed" mark.
    Any later edit withdraws the approval."""
    await run_in_threadpool(_get, ctx, draft_id)
    rows = await run_in_threadpool(
        lambda: ctx.db().table(TABLE).update({"approved_at": datetime.now(timezone.utc).isoformat()}).eq("id", str(draft_id)).execute().data
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    await _audit(ctx, request, AuditAction.APPROVE_DRAFT, str(draft_id))
    return await run_in_threadpool(_get, ctx, draft_id)


@router.delete("/{draft_id}/approve")
async def withdraw_draft_approval(draft_id: UUID, request: Request, ctx: OrgContext = Depends(get_org_context)):
    rows = await run_in_threadpool(
        lambda: ctx.db().table(TABLE).update({"approved_at": None}).eq("id", str(draft_id)).execute().data
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    await _audit(ctx, request, AuditAction.WITHDRAW_DRAFT_APPROVAL, str(draft_id))
    return await run_in_threadpool(_get, ctx, draft_id)


@router.patch("/{draft_id}")
def update_draft(draft_id: UUID, payload: DraftUpdate, ctx: OrgContext = Depends(get_org_context)):
    """Save edits from the clause editor. Missing information is recomputed from the placeholders left."""
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update")
    if payload.content is not None:
        text = "\n".join([p for s in payload.content.sections for p in [s.heading or "", *s.paragraphs]] + payload.content.signature_block)
        changes["missing"] = sorted({m.group(0)[2:-2] for m in drafting_engine.PLACEHOLDER.finditer(text)})
    rows = ctx.db().table(TABLE).update(changes).eq("id", str(draft_id)).execute().data
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    return rows[0]


@router.delete("/{draft_id}")
async def delete_draft(draft_id: UUID, request: Request, reason: ReasonQuery = None, ctx: OrgContext = Depends(get_org_context)):
    """Move to the trash (restorable for 30 days), or ask a partner or owner to (202) when your role can't."""
    draft = await run_in_threadpool(_get, ctx, draft_id)
    return await delete_response(ctx, request, "draft", draft_id, label=draft.get("title"), reason=reason)


@router.get(
    "/{draft_id}/export",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}, DOCX_MEDIA_TYPE: {}}}},
)
async def export_draft(
    draft_id: UUID,
    request: Request,
    format: Literal["docx", "pdf"] = Query("docx"),
    unresolved: Literal["keep", "remove"] = Query("keep", description="Citations that couldn't be verified: keep them, or "
                                                                     "replace each with a placeholder to fill in"),
    ctx: OrgContext = Depends(get_org_context),
):
    """Download as an editable Word document (.docx) or a PDF. Unfilled placeholders are highlighted.

    Until a lawyer approves the draft, every page is marked "AI draft · unreviewed". Exporting is never
    blocked: what was unresolved at export time, and the choice made about it, is logged.
    """
    draft = await run_in_threadpool(_get, ctx, draft_id)
    sources, documents = await _draft_sources(ctx, draft)
    report = draft_check.checklist(draft, sources, documents)
    if unresolved == "remove":
        draft = draft_check.without_unresolved(draft, sources)
    if format == "docx":
        data = await run_in_threadpool(drafting_engine.to_docx, draft)
        media_type = DOCX_MEDIA_TYPE
    else:
        data = await run_in_threadpool(drafting_engine.to_pdf, draft)
        media_type = "application/pdf"
    await _audit(
        ctx, request, AuditAction.EXPORT_DRAFT, str(draft_id), format=format, approved=report["approved"],
        unresolved_citations=[c["text"] for c in report["unresolved_citations"]], unresolved_choice=unresolved,
        mismatches=len(report["mismatches"]), missing=len(report["missing"]),
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{drafting_engine.export_filename(draft, format)}"',
            "Cache-Control": "no-store",
        },
    )

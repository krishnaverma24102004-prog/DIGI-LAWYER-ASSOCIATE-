"""Bulk document review: the same questions asked of many documents, answered as a grid.

Each document is PII-masked and reviewed in one Claude call that answers every question with the
passage it rests on. That passage is then checked against the document text (the same fuzzy match
the contradiction analyzer uses), so every cell says whether its source quote is really there:
the lawyer can trust a verified cell and knows exactly which ones to read for themselves.

Cells are stored as they finish, so the grid fills in while the review runs.
"""

import asyncio
import csv
import io
import logging
import re
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool
from supabase import Client

from app.core.guardrails import PiiMasker, mask_pii
from app.services import anthropic_service, document_service, evidence_service, governing_law, jurisdiction_service

logger = logging.getLogger(__name__)

GRIDS = "review_grids"
CELLS = "review_cells"
MAX_DOCUMENTS = 50
MAX_QUESTIONS = 15
DOCUMENT_CHARS = 60_000  # longer documents are reviewed on their most relevant clauses
CONCURRENCY = 3
NOT_STATED = "Not stated in the document"
KINDS = ("text", "yes_no", "date", "amount", "duration")

PRESETS: dict[str, list[dict]] = {
    "Commercial contract (India)": [
        {"question": "Who are the parties?", "kind": "text"},
        {"question": "What is the effective date?", "kind": "date"},
        {"question": "What is the term, and does it renew automatically?", "kind": "duration"},
        {"question": "How much notice is needed to terminate, and on what grounds?", "kind": "duration"},
        {"question": "Is liability capped? At what amount?", "kind": "amount"},
        {"question": "Is there an indemnity, and who gives it?", "kind": "text"},
        {"question": "What is the governing law and jurisdiction?", "kind": "text"},
        {"question": "Is there an arbitration clause? What is the seat?", "kind": "text"},
        {"question": "Is consent needed to assign the contract?", "kind": "yes_no"},
        {"question": "Is it stamped, or does it say stamp duty is payable?", "kind": "yes_no"},
    ],
    "Lease / leave and licence": [
        {"question": "Who are the licensor/landlord and licensee/tenant?", "kind": "text"},
        {"question": "What is the monthly rent or licence fee?", "kind": "amount"},
        {"question": "What is the security deposit, and when is it refunded?", "kind": "amount"},
        {"question": "What is the term and the lock-in period?", "kind": "duration"},
        {"question": "How much notice ends the agreement early?", "kind": "duration"},
        {"question": "What is the rent escalation?", "kind": "text"},
        {"question": "Who pays maintenance and repairs?", "kind": "text"},
        {"question": "Is the agreement registered?", "kind": "yes_no"},
    ],
    "Employment agreement": [
        {"question": "Who is the employer and the employee?", "kind": "text"},
        {"question": "What is the annual compensation (CTC)?", "kind": "amount"},
        {"question": "What is the notice period for resignation and for termination?", "kind": "duration"},
        {"question": "Is there a non-compete or non-solicitation clause, and for how long?", "kind": "duration"},
        {"question": "Is there a probation period?", "kind": "duration"},
        {"question": "Who owns intellectual property created during employment?", "kind": "text"},
        {"question": "Is there a bond or training-cost recovery clause?", "kind": "yes_no"},
    ],
    "NDA": [
        {"question": "Is it mutual or one-way?", "kind": "text"},
        {"question": "How is confidential information defined?", "kind": "text"},
        {"question": "How long do the confidentiality obligations last?", "kind": "duration"},
        {"question": "What are the exclusions from confidentiality?", "kind": "text"},
        {"question": "What is the governing law?", "kind": "text"},
    ],
}


class ReviewError(ValueError):
    pass


def normalize_questions(raw: list, start: int = 1) -> list[dict]:
    """Questions as {id, question, kind}; strings are text questions."""
    questions = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            item = {"question": item}
        text = " ".join(str(item.get("question", "")).split())[:500]
        if not text:
            continue
        kind = item.get("kind") if item.get("kind") in KINDS else "text"
        questions.append({"id": f"q{start + i}", "question": text, "kind": kind})
    return questions


# ----------------------------------------------------------------------------- storage (RLS)


def create_grid(db: Client, title: str, document_ids: list[str], questions: list[dict], jurisdiction: str | None) -> dict:
    grid = db.table(GRIDS).insert(
        {"title": title, "document_ids": document_ids, "questions": questions, "jurisdiction": jurisdiction}
    ).execute().data[0]
    _pending(db, grid["id"], document_ids, questions)
    return grid


def _pending(db: Client, grid_id: str, document_ids: list[str], questions: list[dict]) -> None:
    rows = [{"grid_id": grid_id, "document_id": d, "question_id": q["id"], "status": "pending"} for d in document_ids for q in questions]
    for start in range(0, len(rows), 500):
        db.table(CELLS).upsert(rows[start : start + 500], on_conflict="grid_id,document_id,question_id").execute()


def add_questions(db: Client, grid: dict, raw: list) -> list[dict]:
    existing = grid["questions"]
    if len(existing) + len(raw) > MAX_QUESTIONS:
        raise ReviewError(f"A review has at most {MAX_QUESTIONS} questions")
    start = max([int(q["id"][1:]) for q in existing] or [0]) + 1
    added = normalize_questions(raw, start)
    db.table(GRIDS).update({"questions": [*existing, *added]}).eq("id", grid["id"]).execute()
    _pending(db, grid["id"], grid["document_ids"], added)
    return added


def get_grid(db: Client, grid_id: str) -> dict | None:
    rows = db.table(GRIDS).select("*").eq("id", grid_id).limit(1).execute().data
    if not rows:
        return None
    grid = rows[0]
    grid["cells"] = db.table(CELLS).select("*").eq("grid_id", grid_id).execute().data
    documents = (db.table("documents").select("id, filename, governing_law").in_("id", grid["document_ids"]).execute().data
                 if grid["document_ids"] else [])
    by_id = {d["id"]: d for d in documents}
    unread = [d["id"] for d in documents if d.get("governing_law") is None]
    if unread:  # uploaded before governing laws were recorded: read them now
        for row in db.table("documents").select("id, extracted_text").in_("id", unread).execute().data:
            by_id[row["id"]]["governing_law"] = governing_law.detect(row.get("extracted_text"))
    # Each document's own governing law vs the grid's jurisdiction; enforceability answers get the caveat.
    profile = jurisdiction_service.get_profile(grid.get("jurisdiction"))
    grid["documents"] = []
    caveats: dict[str, str] = {}
    for doc_id in grid["document_ids"]:
        doc = by_id.get(doc_id) or {}
        law = governing_law.assess(doc.get("governing_law"), profile)
        if law["caveat"]:
            caveats[doc_id] = law["caveat"]
        grid["documents"].append({"id": doc_id, "filename": doc.get("filename", "(removed)"), "governing_law": law})
    for cell in grid["cells"]:
        if cell["document_id"] in caveats and governing_law.concerns_enforceability(cell.get("answer")):
            cell["jurisdiction_caveat"] = caveats[cell["document_id"]]
    cells = grid["cells"]
    grid["progress"] = {
        "total": len(cells),
        "done": sum(c["status"] == "done" for c in cells),
        "errors": sum(c["status"] == "error" for c in cells),
        "verified": sum(bool(c.get("verified")) for c in cells),
    }
    return grid


def list_grids(db: Client) -> list[dict]:
    return db.table(GRIDS).select("id, title, document_ids, questions, created_at, updated_at").order("created_at", desc=True).limit(100).execute().data


# ----------------------------------------------------------------------------- running


def _document_text(text: str, questions: list[dict]) -> str:
    if len(text) <= DOCUMENT_CHARS:
        return text
    return document_service.select_relevant_clauses(text, " ".join(q["question"] for q in questions), DOCUMENT_CHARS)


def _cell(grid_id: str, document_id: str, question_id: str, **fields) -> dict:
    return {"grid_id": grid_id, "document_id": document_id, "question_id": question_id,
            "updated_at": datetime.now(timezone.utc).isoformat(), **fields}


async def review_one(db: Client, access_token: str, org_id: str, grid: dict, document_id: str, questions: list[dict]) -> list[dict]:
    """Answer `questions` from one document and store the cells. Never raises: failures become error cells."""
    jurisdiction = jurisdiction_service.get_profile(grid.get("jurisdiction"))
    try:
        row = await run_in_threadpool(document_service.get_document, access_token, document_id, include_text=True, org_id=org_id)
        if row is None:
            raise ReviewError("Document not found")
        masker = PiiMasker()
        masked = (await run_in_threadpool(mask_pii, _document_text(row.get("extracted_text") or "", questions), masker)).text
        if not masked.strip():
            raise ReviewError("The document has no text")
        review = await anthropic_service.review_document(masked, questions, jurisdiction=jurisdiction)
        answers = {a.question_id: a for a in review.answers}
        cells = []
        for q in questions:
            a = answers.get(q["id"])
            if a is None:
                cells.append(_cell(grid["id"], document_id, q["id"], status="error", error="No answer returned"))
                continue
            quote = (a.quote or "").strip() or None
            # The quote must really be in the (masked) text the model was shown.
            match = evidence_service.quote_match(quote, masked) if quote else None
            verified = match is not None
            cells.append(_cell(
                grid["id"], document_id, q["id"], status="done", error=None,
                # Stored for the firm with the client's details restored.
                answer=masker.unmask(a.answer.strip()) or NOT_STATED,
                quote=masker.unmask(quote) if quote else None,
                verified=verified if quote else None,
                quote_match=match.kind if match else None,
                quote_differs=[masker.unmask(w) for w in match.differs] if match else [],
                confidence=a.confidence,
            ))
    except Exception as exc:
        logger.warning("Review of document %s in grid %s failed: %s", document_id, grid["id"], exc)
        message = str(exc) if isinstance(exc, ReviewError) else "The review failed; retry it"
        cells = [_cell(grid["id"], document_id, q["id"], status="error", error=message) for q in questions]
    await run_in_threadpool(lambda: db.table(CELLS).upsert(cells, on_conflict="grid_id,document_id,question_id").execute())
    return cells


async def run_review(db: Client, access_token: str, org_id: str, grid: dict, questions: list[dict] | None = None,
                     document_ids: list[str] | None = None) -> None:
    """Review every document (or `document_ids`) for every question (or `questions`), a few at a time."""
    questions = questions or grid["questions"]
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def one(document_id: str):
        async with semaphore:
            await review_one(db, access_token, org_id, grid, document_id, questions)

    await asyncio.gather(*(one(d) for d in (document_ids or grid["document_ids"])))


def to_csv(grid: dict) -> str:
    cells = {(c["document_id"], c["question_id"]): c for c in grid["cells"]}
    out = io.StringIO()
    writer = csv.writer(out)
    header = ["Document"]
    for q in grid["questions"]:
        header += [q["question"], f"{q['question']} (source)", f"{q['question']} (verified)"]
    writer.writerow(header)
    for d in grid["documents"]:
        row = [d["filename"]]
        for q in grid["questions"]:
            c = cells.get((d["id"], q["id"]), {})
            verified = {True: "close match - check" if c.get("quote_match") == "close" else "yes",
                        False: "NO - check"}.get(c.get("verified"), "")
            row += [c.get("answer") or c.get("error") or "", c.get("quote") or "", verified]
        writer.writerow(row)
    return out.getvalue()


def filename(grid: dict) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", grid["title"].lower()).strip("-")[:60] or "review"
    return f"{slug}.csv"

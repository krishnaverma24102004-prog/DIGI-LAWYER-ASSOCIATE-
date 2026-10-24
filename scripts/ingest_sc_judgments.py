"""Load Supreme Court of India judgments into the shared corpus (migration 008).

Source: the public AWS Open Data bucket `indian-supreme-court-judgments` (judgments from 1950,
scraped from the Supreme Court's website; metadata per year as Parquet, judgments as PDFs).

Two levels:

  index      every judgment's title, parties, report citation ([2024] 10 S.C.R. 108) and
             neutral citation (2024 INSC 735) into `legal_authorities`, so the citation check
             recognises real cases. Fast: one small Parquet file per year, no PDFs.
  full text  for the years in --full-text, also download each judgment's PDF and chunk + embed
             its text into the shared knowledge base (`legal_knowledge_base`, org_id NULL), so the
             researcher agent can retrieve and cite it. Slow: ~1 MB per judgment, local embeddings.

Usage (from the project folder, with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env):

  python scripts/ingest_sc_judgments.py --years 1950-2026
  python scripts/ingest_sc_judgments.py --years 2024 --full-text 2024 --limit 50

Re-running is safe: judgments already indexed or ingested are skipped.
"""

import argparse
import io
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_supabase_admin  # noqa: E402
from app.services import citation_service, rag_service  # noqa: E402

logger = logging.getLogger("ingest_sc")

BUCKET = "https://indian-supreme-court-judgments.s3.amazonaws.com"
BATCH = 500


def parse_years(spec: str) -> list[int]:
    years: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            start, end = part.split("-")
            years += range(int(start), int(end) + 1)
        elif part.strip():
            years.append(int(part))
    return years


def pdf_url(year: int, path: str) -> str:
    return f"{BUCKET}/data/pdf/year={year}/english/{path}_EN.pdf"


def read_metadata(client: httpx.Client, year: int) -> list[dict]:
    import pyarrow.parquet as pq

    response = client.get(f"{BUCKET}/metadata/parquet/year={year}/metadata.parquet")
    if response.status_code == 404:
        return []
    response.raise_for_status()
    columns = ["title", "petitioner", "respondent", "citation", "case_id", "decision_date", "path", "court"]
    table = pq.read_table(io.BytesIO(response.content))
    return table.select([c for c in columns if c in table.schema.names]).to_pylist()


def _date(value: str | None) -> str | None:
    try:
        return datetime.strptime(value or "", "%d-%m-%Y").date().isoformat()
    except ValueError:
        return None


def authority_row(year: int, judgment: dict) -> dict | None:
    title = " ".join((judgment.get("title") or "").split())
    path = judgment.get("path")
    if not title or not path:
        return None
    citation = (judgment.get("citation") or "").strip() or None
    neutral = (judgment.get("case_id") or "").strip() or None
    keys = sorted({citation_service._case_key(c) for c in (citation, neutral) if c})
    return {
        "kind": "case",
        "court": judgment.get("court") or "Supreme Court of India",
        "title": title[:500],
        "citation": citation,
        "neutral_citation": neutral,
        "decision_date": _date(judgment.get("decision_date")),
        "jurisdiction_code": "IN",
        "citation_keys": keys,
        "name_tokens": sorted(set(citation_service._name_tokens(title.replace(" versus ", " v. ")))),
        "source_url": pdf_url(year, path),
        "external_id": f"sc:{path}",
    }


def index_year(db, client: httpx.Client, year: int) -> list[dict]:
    rows = [r for r in (authority_row(year, j) for j in read_metadata(client, year)) if r]
    for start in range(0, len(rows), BATCH):
        db.table("legal_authorities").upsert(rows[start : start + BATCH], on_conflict="external_id").execute()
    logger.info("%s: indexed %d judgments", year, len(rows))
    return rows


def pdf_text(data: bytes) -> str:
    """The PDF's text layer (no OCR: older scanned judgments are skipped rather than sent anywhere)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def ingest_full_text(db, client: httpx.Client, rows: list[dict], limit: int | None) -> int:
    embedder = rag_service.get_embedder()
    done = 0
    for row in rows:
        if limit is not None and done >= limit:
            break
        existing = db.table("legal_authorities").select("source_id").eq("external_id", row["external_id"]).limit(1).execute().data
        if existing and existing[0].get("source_id"):
            continue
        response = client.get(row["source_url"])
        if response.status_code != 200:
            logger.warning("No PDF for %s (%s)", row["title"], response.status_code)
            continue
        text = pdf_text(response.content)
        if len(text) < 500:
            logger.warning("No text layer in %s; skipped", row["title"])
            continue
        chunks = rag_service.chunk_text(text)
        heading = f"{row['title']}, {row['citation'] or row['neutral_citation'] or ''}".strip(", ")
        vectors = embedder.embed_passages([f"{heading}\n\n{chunk}" for chunk in chunks])
        source_id = str(uuid.uuid4())
        metadata = {
            "citation": row["citation"] or row["neutral_citation"],
            "neutral_citation": row["neutral_citation"],
            "court": row["court"],
            "decision_date": row["decision_date"],
            "jurisdiction": "India",
            "jurisdiction_code": "IN",
            "source_url": row["source_url"],
            "corpus": "sc_judgments",
            "chunk_count": len(chunks),
        }
        records = [
            {"org_id": None, "source_id": source_id, "chunk_index": i, "title": row["title"][:300], "content": chunk,
             "vector_embedding": vector, "metadata": metadata, "created_by": None}
            for i, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]
        for start in range(0, len(records), rag_service.INSERT_BATCH_SIZE):
            db.table(rag_service.TABLE).insert(records[start : start + rag_service.INSERT_BATCH_SIZE]).execute()
        db.table("legal_authorities").update({"source_id": source_id}).eq("external_id", row["external_id"]).execute()
        done += 1
        logger.info("Ingested %s (%d chunks)", heading, len(chunks))
    return done


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--years", required=True, help="e.g. 1950-2026 or 2023,2024")
    parser.add_argument("--full-text", default="", help="years whose judgments to embed in full, e.g. 2024")
    parser.add_argument("--limit", type=int, default=None, help="max judgments to embed per full-text year")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    db = get_supabase_admin()
    full_text_years = set(parse_years(args.full_text)) if args.full_text else set()
    total = embedded = 0
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for year in parse_years(args.years):
            rows = index_year(db, client, year)
            total += len(rows)
            if year in full_text_years:
                embedded += ingest_full_text(db, client, rows, args.limit)
    logger.info("Done: %d judgments indexed, %d embedded in full", total, embedded)


if __name__ == "__main__":
    main()

"""Legal RAG: an org's statutes, case law and firm precedents, searchable by meaning.

Ingestion splits a text into overlapping chunks, embeds each one locally with fastembed
(no client data is sent to a third-party embedding API), and stores them in
public.legal_knowledge_base. Retrieval embeds the recent conversation and calls the
public.match_legal_precedents SQL function (pgvector cosine similarity), which only
ever searches the caller's own organization.

All database access goes through a client acting as the user in their org, so RLS
decides who may read, add or delete knowledge.
"""

import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.concurrency import run_in_threadpool
from supabase import Client

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TABLE = "legal_knowledge_base"
CHUNK_CHARS = 1200  # ~300 tokens: well inside the embedding model's 512-token window
CHUNK_OVERLAP_CHARS = 150
EMBED_BATCH_SIZE = 32
INSERT_BATCH_SIZE = 100
MAX_SOURCE_CHARS = 2_000_000
EXCERPT_CHARS = 400


class RagError(RuntimeError):
    pass


@dataclass(frozen=True)
class Precedent:
    """One matched knowledge-base chunk."""

    id: str
    source_id: str
    title: str
    content: str
    similarity: float
    chunk_index: int = 0
    metadata: dict = field(default_factory=dict)

    def citation(self) -> dict:
        """What the client is shown, and what is saved with the transcript."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "title": self.title,
            "citation": self.metadata.get("citation"),
            "jurisdiction": self.metadata.get("jurisdiction"),
            "url": self.metadata.get("source_url"),
            # From the shared Indian law corpus rather than the firm's own knowledge base.
            "shared": bool(self.metadata.get("shared")),
            "similarity": round(self.similarity, 3),
            "excerpt": self.content[:EXCERPT_CHARS],
        }


@dataclass(frozen=True)
class IngestResult:
    source_id: str
    title: str
    chunk_count: int
    char_count: int


# ----------------------------------------------------------------------------- embeddings


class Embedder:
    """Lazily loaded fastembed model, shared by all requests. Thread-safe to load."""

    def __init__(self, model_name: str, dimensions: int, cache_dir: str | None = None):
        self.model_name = model_name
        self.dimensions = dimensions
        self.cache_dir = cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    if self.cache_dir:
                        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
                    logger.info("Loading embedding model %s", self.model_name)
                    self._model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
        return self._model

    def _check(self, vectors: list[list[float]]) -> list[list[float]]:
        if vectors and len(vectors[0]) != self.dimensions:
            raise RagError(
                f"Embedding model {self.model_name} returns {len(vectors[0])} dimensions but the database "
                f"expects {self.dimensions}. Set EMBEDDING_DIMENSIONS and the vector column to match."
            )
        return vectors

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().passage_embed(texts, batch_size=EMBED_BATCH_SIZE)
        return self._check([v.tolist() for v in vectors])

    def embed_query(self, text: str) -> list[float]:
        return self._check([v.tolist() for v in self._load().query_embed(text)])[0]

    def warm_up(self) -> None:
        self.embed_query("warm up")


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        settings = get_settings()
        _embedder = Embedder(settings.embedding_model, settings.embedding_dimensions, settings.embedding_cache_dir or None)
    return _embedder


# ----------------------------------------------------------------------------- chunking

_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z0-9(\"'§])")


def chunk_text(text: str, max_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """Split legal text into ~max_chars chunks on paragraph, then sentence, boundaries.

    Each chunk after the first starts with the last ~`overlap` characters of the previous
    one, so a provision split across a boundary is still retrievable from either side.
    """
    text = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n")).strip()
    if not text:
        return []

    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            # A single huge "sentence" (tables, run-on clauses) is hard-split.
            pieces.extend(sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap:]
            tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
            current = f"{tail} … {piece}" if overlap and len(tail) + len(piece) + 3 <= max_chars else piece
        else:
            current = piece
    if current:
        chunks.append(current)
    return chunks


# ----------------------------------------------------------------------------- ingestion


def ingest_legal_statutes_and_precedents(
    org_id: str,
    title: str,
    text_content: str,
    *,
    db: Client,
    created_by: str | None = None,
    metadata: dict | None = None,
    embedder: Embedder | None = None,
) -> IngestResult:
    """Chunk, embed and store a statute, case or firm precedent. Blocking.

    `db` must act as the uploading user in `org_id` (RLS checks their role).
    """
    title = title.strip()[:300]
    if not title:
        raise RagError("A title is required")
    if len(text_content) > MAX_SOURCE_CHARS:
        raise RagError(f"Text is too long ({len(text_content):,} characters; limit {MAX_SOURCE_CHARS:,})")
    chunks = chunk_text(text_content)
    if not chunks:
        raise RagError("The text is empty")

    embedder = embedder or get_embedder()
    # The title is embedded with each chunk so "s.12" style fragments keep their context.
    vectors = embedder.embed_passages([f"{title}\n\n{chunk}" for chunk in chunks])

    source_id = str(uuid.uuid4())
    base_metadata = {k: v for k, v in (metadata or {}).items() if v not in (None, "")}
    rows = [
        {
            "org_id": org_id,
            "source_id": source_id,
            "chunk_index": index,
            "title": title,
            "content": chunk,
            "vector_embedding": vector,
            "metadata": {**base_metadata, "chunk_count": len(chunks)},
            **({"created_by": created_by} if created_by else {}),
        }
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    try:
        for start in range(0, len(rows), INSERT_BATCH_SIZE):
            db.table(TABLE).insert(rows[start : start + INSERT_BATCH_SIZE]).execute()
    except Exception:
        # Don't leave half a source behind; it would surface as partial, misleading matches.
        try:
            db.table(TABLE).delete().eq("source_id", source_id).execute()
        except Exception:
            logger.exception("Could not clean up partially ingested source %s", source_id)
        raise
    return IngestResult(source_id=source_id, title=title, chunk_count=len(chunks), char_count=len(text_content))


# ----------------------------------------------------------------------------- retrieval


def retrieve_relevant_precedents(
    org_id: str,
    current_transcript_chunk: str,
    top_k: int = 3,
    *,
    db: Client,
    match_threshold: float | None = None,
    embedder: Embedder | None = None,
    jurisdictions: list[str] | None = None,
) -> list[Precedent]:
    """The org's knowledge-base passages most relevant to what is being said. Blocking.

    Returns at most one passage per source (the best-matching one), so a long statute
    can't crowd out everything else. `jurisdictions` (e.g. ["US-CA", "US"]) limits results
    to passages tagged with one of those codes, plus untagged firm material.
    """
    settings = get_settings()
    query = current_transcript_chunk.strip()[-settings.rag_query_chars :]
    if len(query) < 20 or top_k <= 0:
        return []

    embedding = (embedder or get_embedder()).embed_query(query)
    rows = (
        db.rpc(
            "match_legal_precedents",
            {
                "query_embedding": embedding,
                "match_threshold": settings.rag_match_threshold if match_threshold is None else match_threshold,
                "match_count": top_k * 3,
                "target_org_id": org_id,
                "filter_jurisdictions": jurisdictions,
            },
        )
        .execute()
        .data
        or []
    )

    best_per_source: dict[str, Precedent] = {}
    for row in rows:
        precedent = Precedent(
            id=row["id"],
            source_id=row["source_id"],
            title=row["title"],
            content=row["content"],
            similarity=float(row["similarity"]),
            chunk_index=row.get("chunk_index") or 0,
            metadata=row.get("metadata") or {},
        )
        current = best_per_source.get(precedent.source_id)
        if current is None or precedent.similarity > current.similarity:
            best_per_source[precedent.source_id] = precedent
    return sorted(best_per_source.values(), key=lambda p: p.similarity, reverse=True)[:top_k]


async def aingest_legal_statutes_and_precedents(*args, **kwargs) -> IngestResult:
    return await run_in_threadpool(ingest_legal_statutes_and_precedents, *args, **kwargs)


async def aretrieve_relevant_precedents(*args, **kwargs) -> list[Precedent]:
    return await run_in_threadpool(retrieve_relevant_precedents, *args, **kwargs)


# ----------------------------------------------------------------------------- source management


def list_sources(db: Client) -> list[dict]:
    """One row per source the firm ingested (its first chunk carries the source's metadata).

    The shared corpus (org_id NULL) is searchable by everyone but isn't the firm's to list or delete.
    """
    rows = (
        db.table(TABLE)
        .select("source_id, title, metadata, created_by, created_at")
        .eq("chunk_index", 0)
        .not_.is_("org_id", "null")
        .order("created_at", desc=True)
        .execute()
        .data
    )
    return [{**row, "chunk_count": (row.get("metadata") or {}).get("chunk_count")} for row in rows]

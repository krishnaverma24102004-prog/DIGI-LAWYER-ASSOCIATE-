"""Contract / case document ingestion and prompt context.

Text is extracted once at upload and stored in `documents.extracted_text`, so
consultations can attach a document without re-parsing the file. PDF pages without a
text layer (scans) and uploaded images go through OCR (services/ocr_service.py).
"""

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import PurePath

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import get_settings
from app.database import get_supabase_for_user

logger = logging.getLogger(__name__)

TABLE = "documents"
METADATA_COLUMNS = "id, user_id, org_id, filename, content_type, size_bytes, page_count, char_count, extraction, governing_law, created_at"

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_EXTRACTED_CHARS = 2_000_000
# Documents up to this size go into prompts whole (~40k tokens), where prompt caching makes
# repeated live-analysis calls cheap. Longer ones are cut down to the most relevant clauses.
FULL_CONTEXT_MAX_CHARS = 150_000


class DocumentError(ValueError):
    """The upload can't be used; the message is safe to show the user."""


# A page with less text than this is treated as scanned and sent to OCR.
MIN_TEXT_LAYER_CHARS = 25
IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"II*\x00": "image/tiff",
    b"MM\x00*": "image/tiff",
}


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    content_type: str
    page_count: int | None
    # How the text was obtained: {"methods": {"text": 3, "ocr": 2, "vision": 1}, "ocr_mean_confidence": 87.5}
    extraction: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------- extraction


def clean_filename(filename: str | None) -> str:
    name = PurePath((filename or "").replace("\\", "/")).name.strip()
    return (name or "document")[:255]


def _image_type(data: bytes) -> str | None:
    for signature, media_type in IMAGE_SIGNATURES.items():
        if data.startswith(signature):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def extract_text(filename: str, content_type: str, data: bytes) -> ExtractedDocument:
    """Extract text from a PDF, image or plain-text upload. Blocking: run in a threadpool.

    Scanned PDF pages and images are OCR'd; pages OCR can't read go to Claude vision.
    """
    from app.services import ocr_service

    lower_name = filename.lower()
    extraction: dict = {"methods": {"text": 1}}
    image_type = _image_type(data)
    if data.startswith(b"%PDF-"):
        text, pages, extraction = _extract_pdf(data)
        kind = "application/pdf"
    elif image_type:
        try:
            result = ocr_service.ocr_image_document(data)
        except ocr_service.OcrUnavailable as exc:
            raise DocumentError(str(exc)) from exc
        except Exception as exc:
            raise DocumentError("The image could not be read") from exc
        text, pages, kind, extraction = result.text, len(result.pages), image_type, result.summary()
    elif content_type == "application/pdf" or lower_name.endswith(".pdf"):
        raise DocumentError("The file is not a valid PDF")
    elif data.startswith(b"PK\x03\x04") and (content_type == DOCX_TYPE or lower_name.endswith(".docx")):
        text, pages, kind = _extract_docx(data), None, DOCX_TYPE
    elif content_type.startswith("text/") or lower_name.endswith((".txt", ".md")):
        text, pages, kind = _decode_text(data), None, "text/plain"
    else:
        raise DocumentError("Unsupported file type. Upload a PDF, a Word file (.docx), an image (PNG, JPEG, TIFF, WebP) or a .txt file.")

    text = _normalize(text)
    if len(text) < 20:
        raise DocumentError(
            "No readable text found, even with OCR. Try a clearer scan (300 DPI, flat, well lit)."
        )
    if len(text) > MAX_EXTRACTED_CHARS:
        raise DocumentError(f"Document is too long ({len(text):,} characters; limit {MAX_EXTRACTED_CHARS:,})")
    return ExtractedDocument(text=text, content_type=kind, page_count=pages, extraction=extraction)


def _extract_docx(data: bytes) -> str:
    """Paragraphs and table rows of a Word document, in document order (tables keep their place in a contract)."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError("The file is not a valid Word document") from exc
    lines = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            lines.append(Paragraph(child, document).text)
        elif child.tag.endswith("}tbl"):
            for row in Table(child, document).rows:
                cells = list(dict.fromkeys(cell.text.strip() for cell in row.cells))  # merged cells repeat
                lines.append(" | ".join(c for c in cells if c))
    return "\n".join(lines)


def _extract_pdf(data: bytes) -> tuple[str, int, dict]:
    """Text layer where there is one, OCR for scanned pages."""
    from app.services import ocr_service

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentError("The PDF is password-protected")
        page_count = len(reader.pages)
    except DocumentError:
        raise
    except (PdfReadError, ValueError, OSError) as exc:
        raise DocumentError("The PDF could not be read; it may be damaged") from exc
    except Exception as exc:  # pypdf can raise many types on malformed or encrypted files
        logger.warning("Unexpected PDF read failure: %s", exc)
        raise DocumentError("The PDF could not be read") from exc

    if page_count > MAX_PDF_PAGES:
        raise DocumentError(f"The PDF has {page_count} pages; the limit is {MAX_PDF_PAGES}")

    page_texts: dict[int, str] = {}
    for number, page in enumerate(reader.pages, start=1):
        try:
            page_texts[number] = (page.extract_text() or "").strip()
        except Exception:
            logger.warning("Could not extract text from page %s", number, exc_info=True)
            page_texts[number] = ""

    pages = [ocr_service.PageText(n, t, "text") for n, t in page_texts.items() if len(t) >= MIN_TEXT_LAYER_CHARS]
    scanned = [n for n, t in page_texts.items() if len(t) < MIN_TEXT_LAYER_CHARS]
    if scanned:
        try:
            pages += ocr_service.ocr_pdf_pages(data, scanned)
        except ocr_service.OcrUnavailable as exc:
            if not pages:
                raise DocumentError(str(exc)) from exc
            logger.warning("%d scanned pages skipped: %s", len(scanned), exc)
        except Exception:
            logger.exception("OCR failed")
            if not pages:
                raise DocumentError("OCR of the scanned pages failed") from None
    result = ocr_service.OcrResult(sorted(pages, key=lambda p: p.number))
    summary = result.summary()
    if len(scanned) > get_settings().ocr_max_pages:
        summary["pages_not_ocrd"] = len(scanned) - get_settings().ocr_max_pages
    return result.text, page_count, summary


def _decode_text(data: bytes) -> str:
    if b"\x00" in data[:4096]:
        raise DocumentError("The file looks binary, not plain text")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _normalize(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------------- storage (RLS)


def save_document(access_token: str, row: dict, org_id: str | None = None) -> dict:
    """Insert as the user in their org, so RLS stamps and enforces ownership. Blocking."""
    return get_supabase_for_user(access_token, org_id).table(TABLE).insert(row).execute().data[0]


def list_documents(access_token: str, org_id: str | None = None) -> list[dict]:
    db = get_supabase_for_user(access_token, org_id)
    return db.table(TABLE).select(METADATA_COLUMNS).order("created_at", desc=True).execute().data


def get_document(
    access_token: str, document_id: str, include_text: bool = False, org_id: str | None = None
) -> dict | None:
    """Fetch one of the caller's documents; None if missing or owned by someone else (RLS)."""
    columns = f"{METADATA_COLUMNS}, extracted_text" if include_text else METADATA_COLUMNS
    db = get_supabase_for_user(access_token, org_id)
    rows = db.table(TABLE).select(columns).eq("id", document_id).limit(1).execute().data
    return rows[0] if rows else None


# ---------------------------------------------------------------------------- prompt context


@dataclass(frozen=True)
class DocumentContext:
    """A document attached to a consultation, as it is shown to Claude."""

    document_id: str
    filename: str
    text: str

    @classmethod
    def from_row(cls, row: dict) -> "DocumentContext":
        return cls(document_id=row["id"], filename=row["filename"], text=row["extracted_text"])

    @property
    def is_complete(self) -> bool:
        return len(self.text) <= FULL_CONTEXT_MAX_CHARS

    def prompt_text(self, conversation: str, max_chars: int = FULL_CONTEXT_MAX_CHARS) -> str:
        """The whole document if it fits, else the clauses most relevant to the conversation.

        The whole-document form is identical on every call, which keeps it prompt-cacheable.
        """
        if len(self.text) <= max_chars:
            return self.text
        return select_relevant_clauses(self.text, conversation, max_chars)


_CLAUSE_START = re.compile(
    r"^\s*(?:\[Page \d+\]|(?:section|clause|article|schedule)\s+[\dIVX]+|\d+(?:\.\d+)*[.)]?\s+\S)",
    re.IGNORECASE,
)
_STOPWORDS = {
    "that", "this", "with", "from", "have", "will", "shall", "they", "them", "their", "there", "which",
    "what", "when", "were", "been", "being", "would", "could", "should", "about", "into", "than", "then",
    "your", "yours", "said", "just", "like", "know", "think", "also", "only", "such", "upon", "under",
    "party", "parties", "agreement", "hereby", "herein", "thereof", "pursuant", "yeah", "okay", "really",
}
MAX_CLAUSE_CHARS = 4000


def split_clauses(text: str) -> list[str]:
    """Split a document at blank lines and numbered headings (1., 2.3, Section 4, Article V...)."""
    clauses: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if (not line.strip() or _CLAUSE_START.match(line)) and current:
            clauses.append("\n".join(current))
            current = []
        if line.strip():
            current.append(line)
    if current:
        clauses.append("\n".join(current))
    # Very long unstructured blocks are chopped so one block can't eat the whole budget.
    return [c[i : i + MAX_CLAUSE_CHARS] for c in clauses for i in range(0, len(c), MAX_CLAUSE_CHARS)]


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9'-]{3,}", text.lower()) if w not in _STOPWORDS}


def select_relevant_clauses(text: str, conversation: str, max_chars: int) -> str:
    clauses = split_clauses(text)
    query = _terms(conversation)
    # Most overlapping terms first; ties keep document order, so with no signal the opening clauses win.
    ranked = sorted(range(len(clauses)), key=lambda i: -len(query & _terms(clauses[i])))
    chosen: set[int] = set()
    used = 0
    for i in ranked:
        if used + len(clauses[i]) + 2 > max_chars:
            continue
        chosen.add(i)
        used += len(clauses[i]) + 2
    header = (
        f"[Excerpt: {len(chosen)} of {len(clauses)} sections, chosen for relevance to the conversation. "
        "The full document is longer; do not assume a term is absent just because it is not shown.]"
    )
    return header + "\n\n" + "\n\n".join(clauses[i] for i in sorted(chosen))

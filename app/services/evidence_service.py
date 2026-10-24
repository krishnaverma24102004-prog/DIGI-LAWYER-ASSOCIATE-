"""Deposition and evidence contradiction analysis.

A witness statement (typed or pasted text, a saved consultation/deposition transcript,
an uploaded document, or an audio recording transcribed here) is compared against the
case's other evidence: contracts, FIRs, earlier statements, and the case thread's memory.

Accuracy safeguards:
  * The statement is split into numbered lines, keeping timestamps ("[00:12:34]") and
    speakers, so every finding points to a moment in the deposition.
  * Claude must quote both sides exactly. Each finding is checked: the statement quote must
    appear in the statement (its line number is corrected if Claude pointed at the wrong
    line) and the source quote in the named source. Findings that fail are discarded and
    counted, so invented contradictions never reach the report.
  * Severity scores are computed (high 0.9, medium 0.6, low 0.3), so they are consistent.
  * All texts are PII-masked before reaching Claude; the report is unmasked for the lawyer.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher

from app.core.guardrails import PiiMasker, mask_pii
from app.models.analysis import ContradictionFinding
from app.services.document_service import DocumentContext
from app.services.jurisdiction_service import JurisdictionProfile

SEVERITY_SCORE = {"high": 0.9, "medium": 0.6, "low": 0.3}
MAX_STATEMENT_LINES = 2000
MAX_STATEMENT_CHARS = 150_000
MAX_SOURCES_CHARS = 150_000
MAX_SOURCE_CHARS = 40_000
QUOTE_MATCH = 0.85  # share of a quote that must appear verbatim (after normalization)

_TIMESTAMP = re.compile(r"^\s*[\[(]?(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)[\])]?\s*[-–:]?\s*")
_SPEAKER = re.compile(r"^([A-Z][\w .'-]{0,40}):\s+")
_PAGE = re.compile(r"^\s*\[Page (\d+)\]\s*$")


class EvidenceError(ValueError):
    pass


@dataclass
class StatementLine:
    number: int
    text: str
    timestamp: str | None = None
    speaker: str | None = None
    location: str | None = None  # e.g. "Page 3" for documents


@dataclass
class EvidenceSource:
    id: str  # S1, S2 ... (what Claude cites)
    type: str  # document | transcript | case_memory | text
    title: str
    text: str
    ref_id: str | None = None

    def describe(self) -> dict:
        return {"id": self.id, "type": self.type, "title": self.title, "ref_id": self.ref_id}


@dataclass
class Statement:
    label: str
    lines: list[StatementLine] = field(default_factory=list)
    origin: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


# ----------------------------------------------------------------------------- statements


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def parse_statement_text(text: str, label: str = "Statement") -> Statement:
    """Numbered lines, keeping "[hh:mm:ss]" timestamps, "Speaker:" labels and page markers."""
    lines: list[StatementLine] = []
    page = None
    for raw in text.replace("\r\n", "\n").split("\n"):
        if not raw.strip():
            continue
        page_match = _PAGE.match(raw)
        if page_match:
            page = f"Page {page_match.group(1)}"
            continue
        timestamp = None
        ts = _TIMESTAMP.match(raw)
        if ts and ":" in ts.group(1):
            timestamp = ts.group(1)
            raw = raw[ts.end():]
        speaker = None
        sp = _SPEAKER.match(raw)
        if sp:
            speaker = sp.group(1).strip()
            raw = raw[sp.end():]
        if raw.strip():
            lines.append(StatementLine(len(lines) + 1, raw.strip(), timestamp, speaker, page))
        if len(lines) >= MAX_STATEMENT_LINES:
            break
    if not lines:
        raise EvidenceError("The statement is empty")
    if sum(len(line.text) for line in lines) > MAX_STATEMENT_CHARS:
        raise EvidenceError(f"The statement is too long (limit {MAX_STATEMENT_CHARS:,} characters)")
    return Statement(label=label, lines=lines)


def statement_from_transcript(row: dict) -> Statement:
    """A saved transcript; timestamps come from the session's segment offsets when recorded."""
    statement = parse_statement_text(row.get("content") or "", label=row.get("title") or "Transcript")
    segments = (row.get("metadata") or {}).get("segments") or []
    if len(segments) == len(statement.lines):
        for line, segment in zip(statement.lines, segments):
            if line.timestamp is None and segment.get("offset") is not None:
                line.timestamp = format_seconds(segment["offset"])
    statement.origin = {"type": "transcript", "id": row.get("id")}
    return statement


def transcript_text_from_utterances(utterances: list[dict]) -> str:
    """Deepgram utterances -> "[hh:mm:ss] Speaker N: text" lines."""
    lines = []
    for u in utterances:
        speaker = f"Speaker {int(u['speaker']) + 1}" if u.get("speaker") is not None else "Speaker"
        lines.append(f"[{format_seconds(u.get('start') or 0)}] {speaker}: {u.get('transcript', '').strip()}")
    return "\n".join(line for line in lines if not line.endswith(": "))


# ----------------------------------------------------------------------------- prompt rendering


def render_statement(statement: Statement, masker: PiiMasker) -> str:
    rows = []
    for line in statement.lines:
        attrs = f'n="{line.number}"'
        if line.timestamp:
            attrs += f' time="{line.timestamp}"'
        if line.speaker:
            attrs += f' speaker="{line.speaker}"'
        if line.location:
            attrs += f' location="{line.location}"'
        rows.append(f"<line {attrs}>{mask_pii(line.text, masker).text}</line>")
    return "\n".join(rows)


def prepare_sources(sources: list[EvidenceSource], statement_text: str, masker: PiiMasker) -> list[EvidenceSource]:
    """Mask and trim sources to the budget (long documents keep the parts relevant to the statement)."""
    prepared, used = [], 0
    for source in sources:
        text = source.text
        if len(text) > MAX_SOURCE_CHARS:
            text = DocumentContext(source.ref_id or source.id, source.title, text).prompt_text(statement_text, MAX_SOURCE_CHARS)
        if used + len(text) > MAX_SOURCES_CHARS:
            break
        used += len(text)
        prepared.append(EvidenceSource(source.id, source.type, source.title, mask_pii(text, masker).text, source.ref_id))
    return prepared


def render_sources(sources: list[EvidenceSource]) -> str:
    return "\n\n".join(
        f'<source id="{s.id}" type="{s.type}" title="{s.title.replace(chr(34), chr(39))}">\n{s.text}\n</source>' for s in sources
    )


# ----------------------------------------------------------------------------- verification


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s:'/.-]", " ", text)).strip()


@dataclass(frozen=True)
class QuoteMatch:
    """How a quote was found: word for word ("exact"), or mostly ("close", with the quote's words
    that aren't in the matching passage, for the lawyer to check)."""

    kind: str  # "exact" | "close"
    differs: tuple[str, ...] = ()


def quote_match(quote: str, text: str) -> QuoteMatch | None:
    """None when the quote isn't in the text (verbatim, or a contiguous match of QUOTE_MATCH of it)."""
    quote, text = _normalize(quote), _normalize(text)
    if not quote:
        return None
    if quote in text:
        return QuoteMatch("exact")
    match = SequenceMatcher(None, quote, text, autojunk=False).find_longest_match(0, len(quote), 0, len(text))
    if match.size < QUOTE_MATCH * len(quote):
        return None
    # Words of the quote (even partly) outside the matching passage.
    differs, position = [], 0
    for word in quote.split(" "):
        start = quote.index(word, position)
        position = start + len(word)
        if start < match.a or position > match.a + match.size:
            differs.append(word)
    return QuoteMatch("close", tuple(differs))


def quote_found(quote: str, text: str) -> bool:
    return quote_match(quote, text) is not None


def verify_findings(
    findings: list[ContradictionFinding], statement_lines_masked: dict[int, str], sources: dict[str, EvidenceSource]
) -> tuple[list[ContradictionFinding], int]:
    """Keep findings whose quotes exist; fix wrong statement line numbers. Returns (kept, discarded)."""
    kept, discarded = [], 0
    for f in findings:
        source = sources.get(f.source_id)
        source_match = quote_match(f.source_quote, source.text) if source is not None else None
        if source_match is None:
            discarded += 1
            continue
        line_text = statement_lines_masked.get(f.statement_line)
        statement_match = quote_match(f.statement_quote, line_text) if line_text is not None else None
        if statement_match is None:
            matches = [(n, m) for n, t in statement_lines_masked.items() if (m := quote_match(f.statement_quote, t))]
            if not matches:
                discarded += 1
                continue
            f = f.model_copy(update={"statement_line": matches[0][0]})
            statement_match = matches[0][1]
        kept.append(f.model_copy(update={
            "source_match": source_match.kind, "source_differs": list(source_match.differs),
            "statement_match": statement_match.kind, "statement_differs": list(statement_match.differs),
        }))
    return kept, discarded


# ----------------------------------------------------------------------------- analysis


async def analyze(
    statement: Statement, sources: list[EvidenceSource], *, jurisdiction: JurisdictionProfile | None = None
) -> dict:
    from app.services import anthropic_service

    if not sources:
        raise EvidenceError("Add at least one source to compare against (a document, transcript or case thread)")
    if not anthropic_service.is_configured():
        raise EvidenceError("Contradiction analysis needs ANTHROPIC_API_KEY")

    masker = PiiMasker()
    statement_xml = render_statement(statement, masker)
    masked_lines = {line.number: mask_pii(line.text, masker).text for line in statement.lines}
    prepared = prepare_sources(sources, statement.text, masker)
    by_id = {s.id: s for s in prepared}

    result = await anthropic_service.analyze_contradictions(statement_xml, render_sources(prepared), jurisdiction=jurisdiction)
    kept, discarded = verify_findings(result.contradictions, masked_lines, by_id)

    lines = {line.number: line for line in statement.lines}
    contradictions = []
    for i, f in enumerate(kept, start=1):
        line = lines[f.statement_line]
        source = by_id[f.source_id]
        contradictions.append(
            {
                "id": f"x{i}",
                "statement_line": f.statement_line,
                "timestamp": line.timestamp,
                "speaker": line.speaker,
                "location": line.location,
                "statement_quote": masker.unmask(f.statement_quote),
                "source": source.describe(),
                "source_quote": masker.unmask(f.source_quote),
                "kind": f.kind,
                "severity": f.severity,
                "severity_score": SEVERITY_SCORE[f.severity],
                "explanation": masker.unmask(f.explanation),
                "cross_examination_questions": [masker.unmask(q) for q in f.cross_examination_questions],
                "verified": True,
            }
        )
    contradictions.sort(key=lambda c: (-c["severity_score"], c["statement_line"]))
    return {
        "statement": {"label": statement.label, "line_count": len(statement.lines), **statement.origin},
        "sources": [s.describe() for s in prepared],
        "sources_omitted": [s.describe() for s in sources if s.id not in by_id],
        "contradictions": contradictions,
        "consistent_points": [masker.unmask(p) for p in result.consistent_points],
        "overall_assessment": masker.unmask(result.overall_assessment),
        "discarded_unverified": discarded,
        "generated_at": datetime.now().astimezone().isoformat(),
    }


# ----------------------------------------------------------------------------- audio


async def transcribe_recording(audio: bytes, *, http_client=None) -> dict:
    """Deposition audio -> timestamped, speaker-labelled transcript (Deepgram pre-recorded)."""
    from deepgram import AsyncDeepgramClient

    from app.core.config import get_settings

    settings = get_settings()
    if not settings.deepgram_api_key:
        raise EvidenceError("Audio transcription needs DEEPGRAM_API_KEY")
    kwargs = {"api_key": settings.deepgram_api_key}
    if http_client is not None:
        kwargs["httpx_client"] = http_client
    client = AsyncDeepgramClient(**kwargs)
    try:
        response = await client.listen.v1.media.transcribe_file(
            request=audio,
            model=settings.deepgram_model,
            language=settings.deepgram_language,
            smart_format=True,
            punctuate=True,
            utterances=True,
            diarize=True,
        )
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        raise EvidenceError(f"Transcription failed ({f'HTTP {status}' if status else type(exc).__name__})") from exc

    utterances = [
        {"start": u.start, "end": u.end, "speaker": u.speaker, "transcript": u.transcript}
        for u in (getattr(response.results, "utterances", None) or [])
    ]
    duration = getattr(response.metadata, "duration", None) if getattr(response, "metadata", None) else None
    return {"text": transcript_text_from_utterances(utterances), "utterances": utterances, "duration": duration}

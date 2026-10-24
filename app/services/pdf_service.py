"""Consultation summary report as a downloadable PDF (ReportLab platypus).

Contents: case title and date, AI summary, legal risks color-coded by severity,
contract cross-references (when a document was attached), key facts, follow-up
recommendations, and the speaker-labelled transcript.

Fonts: ReportLab's built-in Helvetica only covers Western European characters. Set
PDF_FONT_PATH / PDF_FONT_BOLD_PATH to TrueType fonts (e.g. Noto Sans) for other scripts;
otherwise a few common system fonts are tried before falling back to Helvetica.
"""

import io
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings

logger = logging.getLogger(__name__)

INK = colors.HexColor("#1D2330")
MUTED = colors.HexColor("#6B7280")
RULE = colors.HexColor("#E3E6EB")
ACCENT = colors.HexColor("#1F3A8A")
HEADER_BG = colors.HexColor("#F3F5F9")

SEVERITY_COLORS = {
    "high": (colors.HexColor("#C62828"), colors.HexColor("#FDECEC")),
    "medium": (colors.HexColor("#B26A00"), colors.HexColor("#FFF4E0")),
    "low": (colors.HexColor("#2E7D32"), colors.HexColor("#E9F5EA")),
}
ALIGNMENT_LABELS = {
    "conflict": ("Conflict", SEVERITY_COLORS["high"]),
    "not_covered": ("Not covered", SEVERITY_COLORS["medium"]),
    "unclear": ("Unclear", (MUTED, HEADER_BG)),
    "consistent": ("Consistent", SEVERITY_COLORS["low"]),
}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

FALLBACK_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
]

_fonts: tuple[str, str] | None = None


def _get_fonts() -> tuple[str, str]:
    """(regular, bold) font names, registering a TrueType font once if one is available."""
    global _fonts
    if _fonts is not None:
        return _fonts

    settings = get_settings()
    candidates = []
    if settings.pdf_font_path:
        candidates.append((settings.pdf_font_path, settings.pdf_font_bold_path or settings.pdf_font_path))
    candidates += FALLBACK_FONT_CANDIDATES

    _fonts = ("Helvetica", "Helvetica-Bold")
    for regular, bold in candidates:
        if not (Path(regular).is_file() and Path(bold).is_file()):
            continue
        try:
            pdfmetrics.registerFont(TTFont("ReportSans", regular))
            pdfmetrics.registerFont(TTFont("ReportSans-Bold", bold))
            pdfmetrics.registerFontFamily("ReportSans", normal="ReportSans", bold="ReportSans-Bold")
            _fonts = ("ReportSans", "ReportSans-Bold")
            break
        except Exception:
            logger.warning("Could not register PDF font %s", regular, exc_info=True)
    return _fonts


def _styles() -> dict[str, ParagraphStyle]:
    regular, bold = _get_fonts()
    base = getSampleStyleSheet()["Normal"]

    def style(name, **kw):
        return ParagraphStyle(name, parent=base, fontName=kw.pop("fontName", regular), textColor=kw.pop("textColor", INK), **kw)

    return {
        "kicker": style("kicker", fontName=bold, fontSize=8.5, leading=11, textColor=ACCENT),
        "title": style("title", fontName=bold, fontSize=20, leading=25, spaceAfter=2),
        "subtitle": style("subtitle", fontSize=10, leading=14, textColor=MUTED),
        "h2": style("h2", fontName=bold, fontSize=13, leading=17, textColor=ACCENT, spaceBefore=14, spaceAfter=6),
        "h3": style("h3", fontName=bold, fontSize=10.5, leading=14, spaceBefore=6, spaceAfter=2),
        "body": style("body", fontSize=9.5, leading=13.5, alignment=TA_LEFT),
        "small": style("small", fontSize=8.5, leading=11.5, textColor=MUTED),
        "cell": style("cell", fontSize=9, leading=12),
        "cell_bold": style("cell_bold", fontName=bold, fontSize=9, leading=12),
        "cell_head": style("cell_head", fontName=bold, fontSize=8.5, leading=11, textColor=MUTED),
        "badge": style("badge", fontName=bold, fontSize=8, leading=10),
        "speaker": style("speaker", fontSize=9, leading=12.5, leftIndent=0, spaceAfter=3),
    }


def _p(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "Unknown"
    return value.astimezone(timezone.utc).strftime("%d %B %Y, %H:%M UTC")


def _format_duration(start: datetime | None, end: datetime | None) -> str | None:
    if not start or not end or end < start:
        return None
    minutes = round((end - start).total_seconds() / 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


_SPEAKER_LINE = re.compile(r"^([^:\n]{1,50}):\s+(.+)$")


def parse_transcript_lines(content: str) -> list[tuple[str | None, str]]:
    """Split stored transcript text ("Speaker 1: ...") back into (speaker, text) pairs."""
    lines = []
    for line in (content or "").splitlines():
        line = line.strip()
        if not line:
            continue
        match = _SPEAKER_LINE.match(line)
        lines.append((match.group(1), match.group(2)) if match else (None, line))
    return lines


def _section_table(rows, col_widths, header_bg=HEADER_BG, extra_styles=()) -> Table:
    table = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_bg),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                *extra_styles,
            ]
        )
    )
    return table


def _summary_flowables(summary: str, s: dict) -> list:
    """Render the plain-text summary, promoting section headings ("Key Facts", "Overview:") to h3."""
    known = {"overview", "key facts", "potential legal issues", "contract analysis", "open questions", "suggested next steps"}
    flowables = []
    for block in re.split(r"\n\s*\n", summary.strip()):
        lines = block.strip().splitlines()
        if not lines:
            continue
        first = lines[0].strip().rstrip(":").strip("#* ").strip()
        if first.lower() in known or (len(first) < 40 and lines[0].strip().endswith(":")):
            flowables.append(_p(first, s["h3"]))
            lines = lines[1:]
        if lines:
            flowables.append(_p("\n".join(line.rstrip() for line in lines), s["body"]))
            flowables.append(Spacer(1, 4))
    return flowables


def build_transcript_report(transcript: dict, document: dict | None = None) -> bytes:
    """Render a consultation report. `transcript` is a `transcripts` row; blocking."""
    s = _styles()
    regular, bold = _get_fonts()
    metadata = transcript.get("metadata") or {}
    analysis = metadata.get("analysis") or {}
    title = transcript.get("title") or "Consultation"
    started = _parse_dt(metadata.get("started_at")) or _parse_dt(transcript.get("created_at"))
    ended = _parse_dt(metadata.get("ended_at"))
    generated = datetime.now(timezone.utc)

    buffer = io.BytesIO()
    page_width, page_height = A4
    margin = 18 * mm
    content_width = page_width - 2 * margin

    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(ACCENT)
        canvas.rect(0, page_height - 6 * mm, page_width, 6 * mm, stroke=0, fill=1)
        canvas.setStrokeColor(RULE)
        canvas.line(margin, 12 * mm, page_width - margin, 12 * mm)
        canvas.setFont(regular, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 8 * mm, "Confidential - prepared for the attorney. AI-generated analysis; verify before relying on it.")
        canvas.drawRightString(page_width - margin, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=title,
        author=get_settings().app_name,
        subject="Consultation summary report",
    )

    story: list = [
        _p("CONSULTATION SUMMARY REPORT", s["kicker"]),
        Spacer(1, 3),
        _p(title, s["title"]),
    ]

    details = [("Date", _format_dt(started))]
    if duration := _format_duration(started, ended):
        details.append(("Duration", duration))
    if metadata.get("practice_area"):
        details.append(("Practice area", metadata["practice_area"]))
    if document:
        pages = f", {document['page_count']} pages" if document.get("page_count") else ""
        details.append(("Contract", f"{document.get('filename', 'Attached document')}{pages}"))
    details.append(("Reference", str(transcript.get("id", ""))))
    details.append(("Generated", _format_dt(generated)))
    meta_table = Table(
        [[_p(k, s["cell_head"]), _p(v, s["cell"])] for k, v in details],
        colWidths=[28 * mm, content_width - 28 * mm],
        hAlign="LEFT",
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), HEADER_BG),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story += [Spacer(1, 8), meta_table]

    # Summary
    story.append(_p("Summary", s["h2"]))
    if transcript.get("summary"):
        story += _summary_flowables(transcript["summary"], s)
    else:
        story.append(_p("No AI summary was generated for this consultation.", s["small"]))

    # Legal risks, most severe first
    issues = sorted(analysis.get("legal_issues") or [], key=lambda i: SEVERITY_ORDER.get(i.get("severity"), 1))
    story.append(_p("Legal Risks", s["h2"]))
    if issues:
        rows = [[_p("Severity", s["cell_head"]), _p("Issue", s["cell_head"]), _p("Area of law", s["cell_head"])]]
        extra = []
        for row_index, issue in enumerate(issues, start=1):
            severity = issue.get("severity") if issue.get("severity") in SEVERITY_COLORS else "medium"
            fg, bg = SEVERITY_COLORS[severity]
            badge_style = ParagraphStyle(f"sev{row_index}", parent=s["badge"], textColor=fg)
            issue_cell = [_p(issue.get("issue"), s["cell_bold"])]
            if issue.get("rationale"):
                issue_cell.append(_p(issue["rationale"], s["small"]))
            if issue.get("authority"):
                issue_cell.append(_p(f"Authority: {issue['authority']}", s["small"]))
            rows.append([_p(severity.upper(), badge_style), issue_cell, _p(issue.get("area_of_law") or "-", s["cell"])])
            extra += [
                ("BACKGROUND", (0, row_index), (0, row_index), bg),
                ("LINEBEFORE", (0, row_index), (0, row_index), 3, fg),
            ]
        story.append(_section_table(rows, [24 * mm, content_width - 64 * mm, 40 * mm], extra_styles=extra))
    else:
        story.append(_p("No legal risks were flagged.", s["small"]))

    # Contract cross-references
    observations = analysis.get("contract_observations") or []
    if document or observations:
        story.append(_p("Contract Cross-Reference", s["h2"]))
        if observations:
            rows = [[_p("Clause", s["cell_head"]), _p("Observation", s["cell_head"]), _p("Status", s["cell_head"])]]
            extra = []
            for row_index, obs in enumerate(observations, start=1):
                label, (fg, bg) = ALIGNMENT_LABELS.get(obs.get("alignment"), ALIGNMENT_LABELS["unclear"])
                status_style = ParagraphStyle(f"al{row_index}", parent=s["badge"], textColor=fg)
                rows.append([_p(obs.get("clause"), s["cell_bold"]), _p(obs.get("observation"), s["cell"]), _p(label, status_style)])
                extra.append(("BACKGROUND", (2, row_index), (2, row_index), bg))
            story.append(_section_table(rows, [38 * mm, content_width - 64 * mm, 26 * mm], extra_styles=extra))
        else:
            story.append(_p("No statements were cross-referenced against the contract.", s["small"]))

    # Knowledge-base authorities matched during the consultation
    citations = metadata.get("citations") or []
    if citations:
        story.append(_p("Legal Authorities Considered", s["h2"]))
        story.append(_p("Retrieved from the firm's knowledge base as relevant to the conversation; confirm applicability.", s["small"]))
        story.append(Spacer(1, 4))
        rows = [[_p("Authority", s["cell_head"]), _p("Relevant passage", s["cell_head"]), _p("Match", s["cell_head"])]]
        for c in citations:
            label = [_p(c.get("title"), s["cell_bold"])]
            if c.get("citation"):
                label.append(_p(c["citation"], s["small"]))
            if c.get("jurisdiction"):
                label.append(_p(c["jurisdiction"], s["small"]))
            similarity = c.get("similarity")
            match = f"{round(similarity * 100)}%" if isinstance(similarity, (int, float)) else "-"
            rows.append([label, _p(c.get("excerpt"), s["cell"]), _p(match, s["cell"])])
        story.append(_section_table(rows, [48 * mm, content_width - 66 * mm, 18 * mm]))

    # Key facts
    facts = analysis.get("key_facts") or []
    story.append(_p("Key Facts", s["h2"]))
    if facts:
        rows = [[_p("Fact", s["cell_head"]), _p("Category", s["cell_head"])]]
        rows += [[_p(f.get("fact"), s["cell"]), _p((f.get("category") or "-").title(), s["small"])] for f in facts]
        story.append(_section_table(rows, [content_width - 34 * mm, 34 * mm]))
    else:
        story.append(_p("No key facts were extracted.", s["small"]))

    # Follow-up recommendations
    questions = analysis.get("follow_up_questions") or []
    story.append(_p("Follow-up Recommendations", s["h2"]))
    if questions:
        story += [_p(f"{n}.  {q}", s["body"]) for n, q in enumerate(questions, start=1)]
    else:
        story.append(_p("No open follow-up questions.", s["small"]))

    # Transcript
    story.append(_p("Transcript", s["h2"]))
    lines = parse_transcript_lines(transcript.get("content", ""))
    if lines:
        for speaker, text in lines:
            if speaker:
                story.append(Paragraph(f'<font name="{bold}">{escape(speaker)}:</font> {escape(text)}', s["speaker"]))
            else:
                story.append(_p(text, s["speaker"]))
    else:
        story.append(_p("The transcript is empty.", s["small"]))

    # Keep the title block from splitting from the first section on odd page sizes.
    story[0:3] = [KeepTogether(story[0:3])]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def report_filename(transcript: dict) -> str:
    title = transcript.get("title") or "consultation"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()[:60] or "consultation"
    date = (_parse_dt(transcript.get("created_at")) or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return f"{slug}-{date}.pdf"


def build_erasure_certificate(item: dict, *, org_name: str, people: dict[str, str], reference: str) -> bytes:
    """A record that a trashed item was erased: what, who deleted and approved it, and when.

    `item` is a `trash_items` row (after purge); `people` maps user ids to display names.
    """
    s = _styles()
    buffer = io.BytesIO()
    margin = 18 * mm
    content_width = A4[0] - 2 * margin
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=18 * mm, bottomMargin=18 * mm,
        title="Certificate of erasure", author=get_settings().app_name,
    )

    def person(user_id: object) -> str:
        if not user_id:
            return "-"
        return people.get(str(user_id)) or str(user_id)

    automatic = item.get("purged_by") is None
    rows = [
        ("Organization", org_name),
        ("Record", f"{item.get('kind', '').replace('_', ' ')}: {item.get('title') or '(untitled)'}"),
        ("Record id", str(item.get("item_id", ""))),
        ("Deletion requested by", person(item.get("requested_by"))),
        ("Moved to trash by", person(item.get("deleted_by"))),
        ("Moved to trash on", _format_dt(_parse_dt(item.get("deleted_at")))),
        ("Reason", item.get("reason") or "-"),
        ("Erased on", _format_dt(_parse_dt(item.get("purged_at")))),
        ("Erased by", "Retention schedule (30 days after deletion)" if automatic else person(item.get("purged_by"))),
        ("SHA-256 of erased content", str(item.get("snapshot_sha256", ""))),
        ("Certificate reference", reference),
    ]
    table = Table(
        [[_p(k, s["cell_head"]), _p(v, s["cell"])] for k, v in rows],
        colWidths=[48 * mm, content_width - 48 * mm], hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story = [
        _p("CERTIFICATE OF ERASURE", s["kicker"]),
        Spacer(1, 3),
        _p(item.get("title") or "Erased record", s["title"]),
        _p(f"Issued {_format_dt(datetime.now(timezone.utc))}", s["subtitle"]),
        Spacer(1, 10),
        table,
        Spacer(1, 12),
        _p(
            "The record above, and the rows that depended on it, were permanently removed from the application database. "
            "Only this erasure record remains: it names the people involved and a SHA-256 fingerprint of the erased content, "
            "which proves what was erased without keeping it. Copies held outside the application (downloads, email, "
            "database backups until they expire) are not covered by this certificate.",
            s["small"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()

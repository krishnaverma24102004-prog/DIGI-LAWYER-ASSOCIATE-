"""Contract redlining: clause-by-clause comparison of two versions of a contract.

1. Both texts are split into clauses (numbered headings, blank lines).
2. Clauses are aligned deterministically: identical clauses first, then the most similar
   remaining pairs by word overlap (so renumbered or lightly edited clauses still pair),
   with leftovers reported as added or deleted.
3. Modified clauses get a character-level redline (diff-match-patch, semantic cleanup) for
   the side-by-side green/red view.
4. Claude (the analysis model) assesses each changed clause from the client's side: added
   risks, removed protections, altered liabilities, and a counter-clause where useful. The
   texts are PII-masked first, and the output is unmasked for the lawyer.
5. The overall risk delta is computed from the per-clause assessments (not asked of the
   model), so it is consistent and explainable:
       score = sum(+w for increased, -w for decreased), w = 1 / 2 / 3 for low / medium / high
       Increased if score > 0, Decreased if score < 0, else Neutral.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field

from diff_match_patch import diff_match_patch

from app.core.guardrails import PiiMasker
from app.models.analysis import ClauseRiskAssessment, ContractDiffAnalysis
from app.services.document_service import split_clauses
from app.services.jurisdiction_service import JurisdictionProfile

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 0.4
SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3}
BATCH_CLAUSES = 30
BATCH_CHARS = 60_000

_PAGE_MARKER = re.compile(r"^\s*\[Page \d+\]\s*$", re.MULTILINE)
_LABEL = re.compile(r"^\s*(?:(?:section|clause|article)\s+)?(\d+(?:\.\d+)*|[IVX]+)[.):]?\s", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class Clause:
    index: int
    text: str
    label: str | None = None

    @property
    def normalized(self) -> str:
        return re.sub(r"\s+", " ", self.text).strip().lower()

    @property
    def body(self) -> str:
        """The clause without its number, so renumbering alone isn't a change."""
        return re.sub(r"\s+", " ", _LABEL.sub("", self.text, count=1)).strip().lower()

    @property
    def words(self) -> set[str]:
        return set(_WORD.findall(self.normalized))


@dataclass
class ClauseChange:
    id: str
    status: str  # unchanged | renumbered | modified | added | deleted
    original: Clause | None = None
    revised: Clause | None = None
    similarity: float = 1.0
    inline_diff: list[dict] = field(default_factory=list)
    assessment: ClauseRiskAssessment | None = None

    @property
    def label(self) -> str | None:
        return (self.revised or self.original).label

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "label": self.label,
            "original_text": self.original.text if self.original else None,
            "revised_text": self.revised.text if self.revised else None,
            "similarity": round(self.similarity, 3),
            "inline_diff": self.inline_diff,
            "analysis": self.assessment.model_dump() if self.assessment else None,
        }


def split_contract(text: str) -> list[Clause]:
    text = _PAGE_MARKER.sub("", text)
    clauses = []
    for i, chunk in enumerate(c for c in split_clauses(text) if c.strip()):
        match = _LABEL.match(chunk)
        clauses.append(Clause(index=i, text=chunk.strip(), label=match.group(1).upper() if match else None))
    return clauses


def similarity(a: Clause, b: Clause) -> float:
    wa, wb = a.words, b.words
    if not wa or not wb:
        return 0.0
    score = len(wa & wb) / len(wa | wb)
    if a.label and a.label == b.label:
        score += 0.1  # same clause number: a small nudge, since renumbering is common
    return min(score, 1.0)


def inline_diff(original: str, revised: str) -> list[dict]:
    dmp = diff_match_patch()
    dmp.Diff_Timeout = 2.0
    diffs = dmp.diff_main(original, revised)
    dmp.diff_cleanupSemantic(diffs)
    ops = {-1: "delete", 0: "equal", 1: "insert"}
    return [{"op": ops[op], "text": text} for op, text in diffs if text]


def align(original: list[Clause], revised: list[Clause]) -> list[ClauseChange]:
    """Pair clauses across versions and order the result by the revised document."""
    pairs: dict[int, tuple[int, float]] = {}  # revised index -> (original index, similarity)
    free_original = set(range(len(original)))

    # 1. Identical text apart from numbering (whitespace/case-insensitive), in document order.
    by_text: dict[str, list[int]] = {}
    for i in sorted(free_original):
        by_text.setdefault(original[i].body, []).append(i)
    for j, clause in enumerate(revised):
        candidates = by_text.get(clause.body)
        if candidates:
            i = candidates.pop(0)
            pairs[j] = (i, 1.0)
            free_original.discard(i)

    # 2. Most similar remaining pairs, greedily.
    scored = sorted(
        (
            (similarity(original[i], revised[j]), i, j)
            for j in range(len(revised))
            if j not in pairs
            for i in free_original
        ),
        reverse=True,
    )
    for score, i, j in scored:
        if score < MATCH_THRESHOLD:
            break
        if j in pairs or i not in free_original:
            continue
        pairs[j] = (i, score)
        free_original.discard(i)

    # 3. Walk the revised document; slot each deleted clause after its preceding original neighbour.
    changes: list[ClauseChange] = []
    placed_original: dict[int, int] = {}
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"c{counter}"

    for j, clause in enumerate(revised):
        if j in pairs:
            i, score = pairs[j]
            if original[i].normalized == clause.normalized:
                status = "unchanged"
            elif original[i].body == clause.body:
                status = "renumbered"
            else:
                status = "modified"
            change = ClauseChange(
                id=next_id(),
                status=status,
                original=original[i],
                revised=clause,
                similarity=score,
                inline_diff=[] if status == "unchanged" else inline_diff(original[i].text, clause.text),
            )
            placed_original[i] = len(changes)
        else:
            change = ClauseChange(id=next_id(), status="added", revised=clause, similarity=0.0,
                                  inline_diff=[{"op": "insert", "text": clause.text}])
        changes.append(change)

    for i in sorted(free_original):
        before = [placed_original[k] for k in placed_original if k < i]
        position = (max(before) + 1) if before else 0
        deleted = ClauseChange(id=next_id(), status="deleted", original=original[i], similarity=0.0,
                                inline_diff=[{"op": "delete", "text": original[i].text}])
        changes.insert(position, deleted)
        placed_original = {k: (v + 1 if v >= position else v) for k, v in placed_original.items()}
        placed_original[i] = position
    return changes


# ----------------------------------------------------------------------------- risk


def risk_delta(assessments: list[ClauseRiskAssessment]) -> tuple[str, int]:
    score = 0
    for a in assessments:
        weight = SEVERITY_WEIGHT[a.severity]
        score += weight if a.risk_impact == "increased" else -weight if a.risk_impact == "decreased" else 0
    return ("Increased" if score > 0 else "Decreased" if score < 0 else "Neutral"), score


def _batches(changes: list[ClauseChange]) -> list[list[ClauseChange]]:
    batches, current, size = [], [], 0
    for change in changes:
        length = len(change.original.text if change.original else "") + len(change.revised.text if change.revised else "")
        if current and (len(current) >= BATCH_CLAUSES or size + length > BATCH_CHARS):
            batches.append(current)
            current, size = [], 0
        current.append(change)
        size += length
    if current:
        batches.append(current)
    return batches


def render_changes_for_model(changes: list[ClauseChange], masker: PiiMasker) -> str:
    from app.core.guardrails import mask_pii

    parts = []
    for c in changes:
        attrs = f'id="{c.id}" status="{c.status}"' + (f' label="{c.label}"' if c.label else "")
        original = mask_pii(c.original.text, masker).text if c.original else ""
        revised = mask_pii(c.revised.text, masker).text if c.revised else ""
        parts.append(
            f"<clause {attrs}>\n<original>\n{original}\n</original>\n<revised>\n{revised}\n</revised>\n</clause>"
        )
    return "\n\n".join(parts)


async def compare(
    original_text: str,
    revised_text: str,
    *,
    analyze: bool = True,
    jurisdiction: JurisdictionProfile | None = None,
    our_side: str | None = None,
) -> dict:
    """Full comparison report (see module docstring)."""
    from app.services import anthropic_service

    changes = align(split_contract(original_text), split_contract(revised_text))
    changed = [c for c in changes if c.status in ("modified", "added", "deleted")]

    summary, concerns, analyzed = "", [], False
    if analyze and changed and anthropic_service.is_configured():
        masker = PiiMasker()
        # Masking runs first (sequentially, sharing one masker); the model calls then run in parallel.
        rendered = [await asyncio.to_thread(render_changes_for_model, batch, masker) for batch in _batches(changed)]
        results = await asyncio.gather(
            *(anthropic_service.analyze_contract_changes(xml, jurisdiction=jurisdiction, our_side=our_side) for xml in rendered),
            return_exceptions=True,
        )
        by_id = {c.id: c for c in changed}
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Contract analysis batch failed: %s", result)
                continue
            analyzed = True
            for assessment in result.clauses:
                if assessment.clause_id in by_id:
                    by_id[assessment.clause_id].assessment = _unmask(assessment, masker)
            summary = " ".join(filter(None, [summary, masker.unmask(result.overall_summary)]))
            concerns += [masker.unmask(k) for k in result.key_concerns]

    assessments = [c.assessment for c in changed if c.assessment]
    delta, score = risk_delta(assessments)

    def entry(c: ClauseChange) -> dict:
        return c.to_dict()

    return {
        "clauses": [entry(c) for c in changes],
        "additions": [entry(c) for c in changes if c.status == "added"],
        "deletions": [entry(c) for c in changes if c.status == "deleted"],
        "modifications": [entry(c) for c in changes if c.status == "modified"],
        "risk_delta": delta if analyzed else "Not analyzed",
        "risk_score": score,
        "summary": summary,
        "key_concerns": concerns,
        "recommended_counter_clauses": [
            {
                "clause_id": c.id,
                "label": c.label,
                "text": c.assessment.recommended_counter_clause,
                "rationale": c.assessment.explanation,
            }
            for c in changed
            if c.assessment and c.assessment.recommended_counter_clause
        ],
        "stats": {
            "clauses_original": sum(1 for c in changes if c.original),
            "clauses_revised": sum(1 for c in changes if c.revised),
            "unchanged": sum(1 for c in changes if c.status == "unchanged"),
            "renumbered": sum(1 for c in changes if c.status == "renumbered"),
            "modified": sum(1 for c in changes if c.status == "modified"),
            "added": sum(1 for c in changes if c.status == "added"),
            "deleted": sum(1 for c in changes if c.status == "deleted"),
            "analyzed": len(assessments),
        },
        "jurisdiction": jurisdiction.code if jurisdiction else None,
    }


def _unmask(a: ClauseRiskAssessment, masker: PiiMasker) -> ClauseRiskAssessment:
    return a.model_copy(
        update={
            "change_summary": masker.unmask(a.change_summary),
            "explanation": masker.unmask(a.explanation),
            "recommended_counter_clause": masker.unmask(a.recommended_counter_clause) if a.recommended_counter_clause else None,
        }
    )

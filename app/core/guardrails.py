"""Real-time guardrails around the AI pipeline.

mask_pii(text)
    Replaces high-risk identifiers (SSNs, card and bank numbers, national IDs, passport
    numbers, emails, phone numbers...) with placeholders like [CLIENT_SSN] or [BANK_ACCT_2]
    before text is sent to any external LLM API. Names, places, dates and organizations
    are deliberately kept: legal analysis depends on them. The entity list is
    configurable (PII_ENTITIES). Detection uses Microsoft Presidio with spaCy's small
    English model, plus Presidio's Indian ID recognizers (Aadhaar, PAN, passport, voter ID).

verify_output_safety(response)
    Checks AI-drafted text for definitive legal directives or outcome guarantees
    (unauthorized-practice-of-law risk) and appends a standard disclaimer when found.

Scope: this protects the LLM calls. Raw audio still goes to the speech-to-text provider,
and the firm's own database keeps the unmasked transcript.
"""

import logging
import re
import threading
from dataclasses import dataclass, field

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Presidio entity -> placeholder label.
PLACEHOLDER_LABELS: dict[str, str] = {
    "US_SSN": "CLIENT_SSN",
    "US_ITIN": "TAX_ID",
    "IN_PAN": "TAX_ID",
    "CREDIT_CARD": "CARD_NUMBER",
    "IBAN_CODE": "BANK_ACCT",
    "US_BANK_NUMBER": "BANK_ACCT",
    "IN_AADHAAR": "NATIONAL_ID",
    "UK_NHS": "NATIONAL_ID",
    "US_PASSPORT": "PASSPORT_NO",
    "IN_PASSPORT": "PASSPORT_NO",
    "US_DRIVER_LICENSE": "DRIVER_LICENSE",
    "IN_VOTER": "VOTER_ID",
    "CRYPTO": "CRYPTO_WALLET",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "IP_ADDRESS": "IP_ADDRESS",
}

# When two detections cover the same text with the same score, the higher priority wins
# (an Indian mobile number also passes the UK NHS number checksum; a 12-digit "account number"
# is also Aadhaar-shaped).
ENTITY_PRIORITY = {"PHONE_NUMBER": 1, "US_BANK_NUMBER": 1}


def _india_recognizers() -> list:
    """Formats Presidio's built-in recognizers miss, so that masking errs on the side of privacy."""
    from presidio_analyzer import Pattern, PatternRecognizer

    return [
        # Aadhaar-shaped numbers even when the checksum fails (a typo or a speech-to-text error
        # still identifies the person). The built-in recognizer only accepts valid checksums.
        PatternRecognizer(
            supported_entity="IN_AADHAAR",
            name="InAadhaarFormatRecognizer",
            patterns=[Pattern("aadhaar (4-4-4 digits)", r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)", 0.4)],
            context=["aadhaar", "aadhar", "adhar", "uid", "uidai"],
        ),
        # Bank account numbers (9-18 digits) as people say or type them, in groups ("1234 5678 9012").
        # Built-in recognizers only take unbroken digits; the context words carry it over the threshold.
        PatternRecognizer(
            supported_entity="US_BANK_NUMBER",
            name="GroupedAccountNumberRecognizer",
            # 9 to 18 digits in all (the lookahead), so times and amounts ("10 30", "2 lakh") don't match.
            patterns=[Pattern("grouped account number",
                              r"(?<![\d+])(?=(?:\d[ -]?){9,18}(?![\d]))\d{2,6}(?:[ -]\d{2,6}){1,5}(?![\d])", 0.1)],
            context=["account", "acct", "khata", "bank", "ifsc", "savings", "current", "number", "no"],
        ),
        # Indian mobile numbers, with or without +91 / 0. Presidio's phone recognizer doesn't
        # look for Indian numbers without a country code.
        PatternRecognizer(
            supported_entity="PHONE_NUMBER",
            name="InMobileRecognizer",
            patterns=[Pattern("indian mobile", r"(?<![\d+])(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)", 1.0)],
            context=["phone", "mobile", "call", "whatsapp", "number", "contact"],
        ),
    ]


@dataclass
class MaskResult:
    text: str
    entities: list[dict] = field(default_factory=list)  # [{"type", "placeholder", "start", "end"}] in the input

    @property
    def masked(self) -> bool:
        return bool(self.entities)


class _PresidioEngines:
    """Analyzer + anonymizer, built once (loading spaCy takes ~1s)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._analyzer = None

    def analyzer(self):
        if self._analyzer is None:
            with self._lock:
                if self._analyzer is None:
                    from presidio_analyzer import AnalyzerEngine
                    from presidio_analyzer.nlp_engine import NlpEngineProvider
                    from presidio_analyzer.predefined_recognizers import (
                        InAadhaarRecognizer,
                        InPanRecognizer,
                        InPassportRecognizer,
                        InVoterRecognizer,
                    )

                    settings = get_settings()
                    nlp = NlpEngineProvider(
                        nlp_configuration={
                            "nlp_engine_name": "spacy",
                            "models": [{"lang_code": "en", "model_name": settings.pii_spacy_model}],
                        }
                    ).create_engine()
                    analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
                    for recognizer in (
                        InAadhaarRecognizer(), InPanRecognizer(), InPassportRecognizer(), InVoterRecognizer(), *_india_recognizers()
                    ):
                        analyzer.registry.add_recognizer(recognizer)
                    self._analyzer = analyzer
        return self._analyzer


_engines = _PresidioEngines()


def warm_up() -> None:
    _engines.analyzer().analyze("warm up", language="en")


class PiiMasker:
    """Masks PII with placeholders that stay consistent for one consultation.

    The same account number is always [BANK_ACCT]; a second, different one becomes
    [BANK_ACCT_2], so the model can still tell them apart without seeing either.
    The originals live only in this object's memory and are never logged.
    """

    def __init__(self, entities: list[str] | None = None, threshold: float | None = None):
        settings = get_settings()
        self.entities = entities or settings.pii_entity_list
        self.threshold = settings.pii_score_threshold if threshold is None else threshold
        self._placeholders: dict[tuple[str, str], str] = {}
        self._originals: dict[str, str] = {}  # placeholder -> value as first written
        self._counts: dict[str, int] = {}

    def _placeholder(self, entity_type: str, value: str) -> str:
        label = PLACEHOLDER_LABELS.get(entity_type, entity_type)
        normalized = re.sub(r"[\s\-.]", "", value).lower()
        if label == "PHONE":  # +91 98765 43210, 098765-43210 and 9876543210 are one number
            normalized = re.sub(r"^(?:\+?91|0)(?=[6-9]\d{9}$)", "", normalized)
        key = (label, normalized)
        if key not in self._placeholders:
            self._counts[label] = self._counts.get(label, 0) + 1
            n = self._counts[label]
            self._placeholders[key] = f"[{label}]" if n == 1 else f"[{label}_{n}]"
            self._originals[self._placeholders[key]] = value
        return self._placeholders[key]

    def unmask(self, text: str) -> str:
        """Restore this session's placeholders, for showing a reply to the person who said them.

        Only for display back to the same user: never for text sent to an external service.
        """
        for placeholder, value in sorted(self._originals.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(placeholder, value)
        return text

    def _known_values(self, text: str) -> list:
        """Identifiers already masked earlier in the session, found again in any spacing.

        Presidio relies on context ("account number ...") for some entities; when a client
        repeats a number later without that context, this still catches it.
        """
        from presidio_analyzer import RecognizerResult

        found = []
        for (label, normalized), _placeholder in self._placeholders.items():
            if len(normalized) < 6:
                continue
            pattern = r"(?<![\w])" + r"[\s\-.]?".join(re.escape(ch) for ch in normalized) + r"(?![\w])"
            entity = next((e for e, l in PLACEHOLDER_LABELS.items() if l == label), label)
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                found.append(RecognizerResult(entity_type=entity, start=match.start(), end=match.end(), score=1.0))
        return found

    def mask(self, text: str) -> MaskResult:
        if not text or not text.strip():
            return MaskResult(text=text)
        results = list(
            _engines.analyzer().analyze(text=text, language="en", entities=self.entities, score_threshold=self.threshold)
        )
        results += self._known_values(text)
        # Overlaps: keep the higher-scoring, then higher-priority, then longer span.
        chosen = []
        for r in sorted(results, key=lambda r: (-r.score, -ENTITY_PRIORITY.get(r.entity_type, 0), -(r.end - r.start))):
            if all(r.end <= c.start or r.start >= c.end for c in chosen):
                chosen.append(r)

        entities, parts, cursor = [], [], 0
        for r in sorted(chosen, key=lambda r: r.start):
            placeholder = self._placeholder(r.entity_type, text[r.start : r.end])
            parts += [text[cursor : r.start], placeholder]
            entities.append({"type": r.entity_type, "placeholder": placeholder, "start": r.start, "end": r.end})
            cursor = r.end
        parts.append(text[cursor:])
        return MaskResult(text="".join(parts), entities=entities)


def mask_pii(text: str, masker: PiiMasker | None = None) -> MaskResult:
    """Mask PII in `text`. Pass a session's PiiMasker to keep placeholders consistent across calls."""
    if not get_settings().pii_masking_enabled:
        return MaskResult(text=text)
    return (masker or PiiMasker()).mask(text)


# ----------------------------------------------------------------------------- output safety

LEGAL_DISCLAIMER = (
    "This is general legal information generated by AI, not legal advice. It may be incomplete or "
    "wrong for this jurisdiction or these facts, and must be reviewed by a licensed attorney before "
    "anyone relies on it or it is shared with a client."
)

# Definitive directives addressed to someone, and promises about outcomes. Informational
# phrasing ("the lawyer may want to consider...", "one option is...") is not matched.
_DIRECTIVE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("directive", re.compile(r"\byou (?:must|should|need to|have to|ought to)\s+(?:immediately\s+)?(?:sue|file|sign|not sign|refuse|accept|reject|plead|settle|stop paying|withhold|terminate|fire|evict|testify|stay silent|destroy|delete)\b", re.I)),
    ("directive", re.compile(r"\b(?:do not|don't|never)\s+(?:sign|pay|agree|accept|settle|talk to|speak to|cooperate with|respond to)\b", re.I)),
    ("directive", re.compile(r"\b(?:i|we)\s+(?:advise|recommend|instruct|urge)\s+(?:you|the client)\s+to\b", re.I)),
    ("directive", re.compile(r"\bmy (?:legal )?advice is\b", re.I)),
    ("guarantee", re.compile(r"\byou (?:will|are going to|are certain to|are guaranteed to)\s+(?:win|lose|get|receive|be (?:awarded|convicted|acquitted|evicted))\b", re.I)),
    ("guarantee", re.compile(r"\b(?:guaranteed?|certain(?:ly)?|definitely|100%)\s+(?:to\s+)?(?:win|succeed|prevail|lose|be awarded|be acquitted|be convicted)\b", re.I)),
    ("guarantee", re.compile(r"\byou have an? (?:airtight|open[- ]and[- ]shut|guaranteed|slam[- ]dunk)\s+case\b", re.I)),
    ("legal_conclusion", re.compile(r"\b(?:this|that|it) is (?:definitely|clearly|certainly) (?:illegal|unlawful|a crime|fraud|negligence)\b", re.I)),
]


@dataclass
class SafetyResult:
    text: str
    flagged: bool
    reasons: list[str]
    disclaimer_appended: bool


def verify_output_safety(response: str) -> SafetyResult:
    """Append the legal disclaimer if the response gives directives or guarantees outcomes."""
    reasons = sorted({kind for kind, pattern in _DIRECTIVE_PATTERNS if pattern.search(response or "")})
    if not reasons:
        return SafetyResult(text=response, flagged=False, reasons=[], disclaimer_appended=False)
    if LEGAL_DISCLAIMER in response:
        return SafetyResult(text=response, flagged=True, reasons=reasons, disclaimer_appended=False)
    logger.info("Output safety: appended disclaimer (%s)", ", ".join(reasons))
    return SafetyResult(
        text=f"{response.rstrip()}\n\n{LEGAL_DISCLAIMER}", flagged=True, reasons=reasons, disclaimer_appended=True
    )

"""What the AI may say to the public on its own (WhatsApp and phone intake).

On public channels the AI takes the intake: it asks questions and acknowledges. Anything with legal
substance (the law, a section or case, a deadline or amount, what the person should do, how a matter
will turn out) waits for a lawyer instead. The prompt asks for questions only; this check makes sure,
without relying on the model to follow it:

    safe, reasons = check_reply(text)

A reply is safe when it asks at least one question, cites nothing, gives no directive or prediction,
mentions no deadline, amount or legal consequence, and its other sentences are short acknowledgements.
"""

import re

from app.core.guardrails import LEGAL_DISCLAIMER, verify_output_safety
from app.services import citation_service

MAX_SAFE_CHARS = 600
MAX_STATEMENT_CHARS = 140

# What a lawyer is shown when a reply is held, and what the person hears or reads meanwhile.
HOLDING_MESSAGE = (
    "Thank you, I've noted this. A lawyer from the firm will review your matter and reply here.\n"
    "धन्यवाद, मैंने यह नोट कर लिया है। फर्म के वकील आपके मामले को देखकर यहीं जवाब देंगे।"
)
HOLDING_LINE = (
    "Thank you, I've noted that. A lawyer from the firm will review your matter and get back to you. "
    "Is there anything else you'd like them to know?"
)

_AUTHORITY = re.compile(
    r"\b(?:sections?|secs?\.|s\.\s*\d|articles?|order\s+[ivxl\d]+|rules?\s+\d|clauses?\s+\d|dhara)\b"
    r"|धारा|अनुच्छेद"
    r"|\b(?:IPC|BNS|BNSS|BSA|CrPC|Cr\.P\.C|CPC|POCSO|NDPS|IBC|RERA|NI\s+Act|IT\s+Act)\b"
    r"|\b(?:v\.|vs\.?|versus)\s+[A-Z]",
    re.I,
)
_DEADLINE_OR_AMOUNT = re.compile(
    r"\d+\s*(?:days?|weeks?|months?|years?|yrs?|din|dino|hafte|mahin[ea]|saal|lakhs?|crores?|%|percent)\b"
    r"|\d+\s*(?:दिन|महीन|साल|लाख|करोड़)"
    r"|₹|\bRs\.?\s*\d|\bINR\b|\brupees?\b",
    re.I,
)
# Legal substance in a statement (questions may mention these: "Did you get a legal notice?").
_SUBSTANCE = re.compile(
    r"\b(?:you\s+(?:can|could|may|should|must|need\s+to|have\s+to|are\s+entitled|are\s+eligible|have\s+a\s+right|will\s+(?:get|win|lose|have\s+to))"
    r"|entitled|eligible|liable|liability|punishable|offen[cs]e|illegal|unlawful|legal(?:ly)?\s+(?:right|valid|binding)"
    r"|your\s+rights?|remed(?:y|ies)|compensation|damages|penalt(?:y|ies)|bail|limitation|time[- ]barred|jurisdiction"
    r"|file\s+(?:a\s+)?(?:case|suit|complaint|fir|petition|appeal)|send\s+(?:a\s+)?(?:legal\s+)?notice|approach\s+(?:the\s+)?(?:court|police|forum|commission)"
    r"|under\s+the\s+(?:law|act|code)|the\s+law\s+(?:says|provides|allows)|court\s+(?:will|may|can)"
    r"|sakt[ei]\s+(?:hain|hai|ho)|(?:karna|karni|bhejna|lena|dena|jana)\s+(?:hoga|hogi|chahiye)|kanoon|kanooni|adhikar|haq\s+hai|jamanat|saza)\b"
    r"|सकत[ेी]\s+ह|चाहिए|होगा|कानून|अधिकार|जमानत|सजा|मुकदमा\s+(?:कर|दर्ज)",
    re.I,
)
_SENTENCE = re.compile(r"[^.!?।\n]+[.!?।]*")


def check_reply(text: str | None) -> tuple[bool, list[str]]:
    """Whether the AI may send `text` to a member of the public unreviewed, and if not, why."""
    text = (text or "").replace(LEGAL_DISCLAIMER, "").strip()
    if not text:
        return False, ["empty"]
    reasons: set[str] = set()
    if len(text) > MAX_SAFE_CHARS:
        reasons.add("too_long")
    if "?" not in text:
        reasons.add("not_a_question")
    if _AUTHORITY.search(text) or citation_service.mentions_authority(text):
        reasons.add("cites_law")
    if _DEADLINE_OR_AMOUNT.search(text):
        reasons.add("deadline_or_amount")
    reasons.update(verify_output_safety(text).reasons)  # directive / guarantee / legal_conclusion
    for sentence in (s.strip() for s in _SENTENCE.findall(text)):
        if not sentence or sentence.endswith("?"):
            continue
        if len(sentence) > MAX_STATEMENT_CHARS:
            reasons.add("explains")
        if _SUBSTANCE.search(sentence):
            reasons.add("legal_substance")
    return not reasons, sorted(reasons)


REASON_LABELS = {
    "empty": "nothing to send",
    "too_long": "longer than an intake question",
    "not_a_question": "doesn't ask anything",
    "cites_law": "mentions a law, section or case",
    "deadline_or_amount": "mentions a deadline or amount",
    "directive": "tells the person what to do",
    "guarantee": "predicts an outcome",
    "legal_conclusion": "states a legal conclusion",
    "explains": "explains rather than asks",
    "legal_substance": "contains legal information",
}

"""WhatsApp intake: a client messages the firm, the AI takes the intake, the lawyer can take over.

Per conversation:

  awaiting_consent  the first message gets the firm's greeting and a consent request (the chat is
                    answered by an AI and recorded for a lawyer). Nothing reaches the AI before YES.
  intake            each client message (text, or a transcribed voice note) runs the agent team in
                    intake mode, PII-masked as in a live consultation, in the client's language. A reply
                    that only asks questions goes back on WhatsApp; one with legal substance (the law,
                    deadlines, what to do) is held for the lawyer to approve, edit or discard, and the
                    client gets a holding message (services/intake_guard.py). The chat is kept as a
                    transcript, with the agents' facts and risks, for the lawyer.
  lawyer            the client asked for a lawyer, a lawyer replied from the inbox, or the firm has
                    public intake turned off: the AI stays quiet.

Webhooks have no user session, so this runs with the service role, scoped to the organization that
owns the WhatsApp number (like phone calls). Messages are de-duplicated on Meta's message id.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool

from app.core.guardrails import PiiMasker, mask_pii
from app.database import get_supabase_admin
from app.models.analysis import LiveAnalysis
from app.services import (
    agent_workflow,
    citation_service,
    intake_guard,
    jurisdiction_service,
    rag_service,
    safety_service,
    whatsapp_service,
)
from app.services.agent_workflow import AgentContext
from app.services.prompt_engine import PracticeAreaProfile
from app.services.whatsapp_service import Incoming

logger = logging.getLogger(__name__)

CONSENT_WORDS = {"yes", "y", "haan", "haa", "ha", "han", "hn", "ok", "okay", "agree", "i agree", "हाँ", "हां", "जी", "ji"}
LAWYER_WORDS = {"lawyer", "vakil", "wakil", "advocate", "human", "talk to lawyer", "वकील"}
HISTORY_CHARS = 6000

CONSENT_PROMPT = (
    "{greeting}\n\n"
    "This chat is answered by the firm's AI assistant and recorded so that a lawyer can review it. "
    "Identity numbers you share are hidden from the AI. It gives general legal information, not legal advice.\n"
    "Reply *YES* to continue, or *LAWYER* to wait for a lawyer.\n\n"
    "यह चैट फर्म के AI सहायक द्वारा दी जाती है और वकील की समीक्षा के लिए रिकॉर्ड की जाती है। जारी रखने के लिए *YES* लिखें।"
)
DEFAULT_GREETING = "Namaste! You've reached the firm's legal intake assistant."
CONSENTED = "Thank you. Please tell me about your legal matter: what happened, when, and who is involved. You can also send a voice note."
HANDED_OFF = "Thank you. A lawyer from the firm will reply here soon."

_locks: dict[str, asyncio.Lock] = {}


def _norm(text: str) -> str:
    return re.sub(r"[^\w\sऀ-ॿ]", "", text).strip().lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Service-role reads and writes for one webhook event."""

    def __init__(self, db):
        self.db = db

    def number(self, phone_number_id: str) -> dict | None:
        rows = self.db.table("whatsapp_numbers").select("*").eq("phone_number_id", phone_number_id).eq("enabled", True).limit(1).execute().data
        return rows[0] if rows else None

    def conversation(self, number: dict, wa_id: str, name: str | None) -> dict:
        self.db.table("whatsapp_conversations").upsert(
            {"org_id": number["org_id"], "phone_number_id": number["phone_number_id"], "owner_user_id": number["owner_user_id"],
             "wa_id": wa_id, "client_name": name},
            on_conflict="phone_number_id,wa_id", ignore_duplicates=True,
        ).execute()
        return (self.db.table("whatsapp_conversations").select("*").eq("phone_number_id", number["phone_number_id"])
                .eq("wa_id", wa_id).limit(1).execute().data[0])

    def add_message(self, conversation_id: str, direction: str, sender: str, body: str, kind: str = "text",
                    wa_message_id: str | None = None, *, status: str = "sent", hold_reasons: list[str] | None = None) -> bool:
        """False when this Meta message id was already stored (a webhook retry)."""
        row = {"conversation_id": conversation_id, "direction": direction, "sender": sender, "kind": kind, "body": body}
        if status != "sent":
            row.update(status=status, hold_reasons=hold_reasons or [])
        if wa_message_id:
            row["wa_message_id"] = wa_message_id
            return bool(self.db.table("whatsapp_messages").upsert(row, on_conflict="wa_message_id", ignore_duplicates=True).execute().data)
        self.db.table("whatsapp_messages").insert(row).execute()
        return True

    def messages(self, conversation_id: str) -> list[dict]:
        return (self.db.table("whatsapp_messages").select("id, sender, body, kind, status, created_at").eq("conversation_id", conversation_id)
                .order("created_at").execute().data)

    def message(self, conversation_id: str, message_id: str) -> dict | None:
        rows = (self.db.table("whatsapp_messages").select("*").eq("conversation_id", conversation_id).eq("id", message_id)
                .limit(1).execute().data)
        return rows[0] if rows else None

    def review_message(self, message_id: str, fields: dict) -> bool:
        """Settles a held reply once (sent or discarded); False if someone else already did."""
        return bool(self.db.table("whatsapp_messages").update(fields).eq("id", message_id).eq("status", "pending").execute().data)

    def intake_enabled(self, org_id: str) -> bool:
        return safety_service.public_intake_enabled(self.db, org_id)

    def update(self, conversation_id: str, fields: dict) -> None:
        self.db.table("whatsapp_conversations").update({**fields, "last_message_at": _now()}).eq("id", conversation_id).execute()

    def practice_area(self, number: dict) -> PracticeAreaProfile | None:
        if not number.get("practice_area_id"):
            return None
        rows = (self.db.table("practice_areas").select("id, name, custom_system_prompt, risk_evaluation_rules")
                .eq("id", number["practice_area_id"]).eq("org_id", number["org_id"]).limit(1).execute().data)
        return PracticeAreaProfile.from_row(rows[0]) if rows else None

    def save_transcript(self, conversation: dict, content: str, analysis: dict, consented_at: str | None) -> str:
        row = {
            "title": f"WhatsApp intake: {conversation.get('client_name') or whatsapp_service.to_e164(conversation['wa_id'])}"[:300],
            "content": content,
            "source": "whatsapp",
            "org_id": conversation["org_id"],
            "user_id": conversation["owner_user_id"],
            "metadata": {"channel": "whatsapp", "conversation_id": conversation["id"], "client": whatsapp_service.to_e164(conversation["wa_id"]),
                         "consent_at": consented_at, "analysis": analysis},
        }
        if conversation.get("transcript_id"):
            self.db.table("transcripts").update(row).eq("id", conversation["transcript_id"]).execute()
            return conversation["transcript_id"]
        return self.db.table("transcripts").insert(row).execute().data[0]["id"]


def _line(message: dict) -> str:
    """A line of what was actually said (held or discarded AI replies never reached the client)."""
    if message.get("status", "sent") != "sent":
        return ""
    who = {"client": "Client", "ai": "AI Assistant", "lawyer": "Lawyer"}.get(message["sender"])
    return f"{who}: {message['body']}" if who else ""


async def _reply(store: Store, conversation: dict, text: str, sender: str = "ai") -> None:
    try:
        sent_id = await whatsapp_service.send_text(conversation["phone_number_id"], conversation["wa_id"], text)
    except whatsapp_service.WhatsAppError as exc:
        logger.warning("WhatsApp reply failed in conversation %s: %s", conversation["id"], exc)
        return
    await run_in_threadpool(store.add_message, conversation["id"], "out", sender, text, "text", sent_id)


async def handle(incoming: Incoming, db=None) -> None:
    """Process one incoming WhatsApp message. Never raises (the webhook has already answered)."""
    try:
        await _handle(incoming, Store(db or get_supabase_admin()))
    except Exception:
        logger.exception("WhatsApp message %s failed", incoming.message_id)


async def _handle(incoming: Incoming, store: Store) -> None:
    number = await run_in_threadpool(store.number, incoming.phone_number_id)
    if number is None:
        logger.warning("WhatsApp message to unconfigured number %s", incoming.phone_number_id)
        return
    conversation = await run_in_threadpool(store.conversation, number, incoming.wa_id, incoming.name)
    lock = _locks.setdefault(conversation["id"], asyncio.Lock())
    async with lock:
        body, kind = incoming.text.strip(), incoming.kind
        if kind == "audio":
            try:
                body = await whatsapp_service.transcribe_voice_note(await whatsapp_service.download_media(incoming.media_id))
            except Exception as exc:
                logger.warning("Voice note %s not transcribed: %s", incoming.message_id, exc)
                body = ""
            body = f"[voice note] {body}" if body else "[voice note that could not be transcribed]"
        elif kind == "other":
            body = "[a message type the assistant can't read: photo, document or location]"
        if not await run_in_threadpool(store.add_message, conversation["id"], "in", "client", body, kind, incoming.message_id):
            return  # already handled (Meta retried the webhook)

        # Re-read: an earlier message may have changed the status while this one waited for the lock.
        conversation = (await run_in_threadpool(
            lambda: store.db.table("whatsapp_conversations").select("*").eq("id", conversation["id"]).limit(1).execute().data
        ))[0]
        words = _norm(body)
        status = conversation["status"]
        if status in ("lawyer", "closed"):
            await run_in_threadpool(store.update, conversation["id"], {})
            return
        if not await run_in_threadpool(store.intake_enabled, number["org_id"]):
            # The firm hasn't turned on public intake: no AI, the lawyer answers from the inbox.
            await run_in_threadpool(store.update, conversation["id"], {"status": "lawyer"})
            await _reply(store, conversation, HANDED_OFF, "system")
            return
        if words in LAWYER_WORDS:
            await run_in_threadpool(store.update, conversation["id"], {"status": "lawyer"})
            await _reply(store, conversation, HANDED_OFF, "system")
            return
        if status == "awaiting_consent":
            if words in CONSENT_WORDS:
                await run_in_threadpool(store.update, conversation["id"], {"status": "intake", "consent_at": _now()})
                await _reply(store, conversation, CONSENTED, "system")
            else:
                await run_in_threadpool(store.update, conversation["id"], {})
                await _reply(store, conversation, CONSENT_PROMPT.format(greeting=number.get("greeting") or DEFAULT_GREETING), "system")
            return
        await _intake_turn(store, number, conversation)


async def _intake_turn(store: Store, number: dict, conversation: dict) -> None:
    messages = await run_in_threadpool(store.messages, conversation["id"])
    consent_at = conversation.get("consent_at") or ""
    # Only what was said after consent reaches the AI: everything after the consent confirmation.
    confirmed = max((i for i, m in enumerate(messages) if m["sender"] == "system" and m["body"] == CONSENTED), default=None)
    after = messages[confirmed + 1 :] if confirmed is not None else [m for m in messages if m["created_at"] > consent_at]
    lines = [line for line in (_line(m) for m in after) if line]
    masker = PiiMasker()
    masked = [(await run_in_threadpool(mask_pii, line, masker)).text for line in lines]
    history, total = [], 0
    for line in reversed(masked):
        if history and total + len(line) > HISTORY_CHARS:
            break
        history.append(line)
        total += len(line) + 1
    history.reverse()

    org_id = number["org_id"]
    admin = store.db
    profile = jurisdiction_service.get_profile(number.get("jurisdiction") or "IN")

    async def research(query: str):
        return await rag_service.aretrieve_relevant_precedents(org_id, query, 3, db=admin,
                                                               jurisdictions=profile.rag_codes if profile else None)

    async def lookup(keys, names):
        return await run_in_threadpool(citation_service.lookup_authorities, admin, keys, names)

    context = AgentContext(
        practice_area=await run_in_threadpool(store.practice_area, number),
        research=research,
        mode="conversation",
        jurisdiction=profile,
        lookup_authorities=lookup,
        intake_only=True,
    )
    state = {**(conversation.get("agent_state") or {}), "transcript_history": "\n".join(history), "current_chunk": masked[-1] if masked else ""}
    result = await agent_workflow.process_audio_chunk_via_agent(state, context)
    final = result.get("final_response") or {}
    keep = {k: result[k] for k in ("extracted_facts", "rag_citations", "legal_risks", "follow_up_questions") if k in result}
    if final.get("message"):
        safe, reasons = intake_guard.check_reply(final["message"])
        if safe:
            await _reply(store, conversation, masker.unmask(final["message"]))
        else:
            await _hold(store, conversation, masker.unmask(final["message"]), reasons, messages)
    analysis = LiveAnalysis.model_validate(final.get("analysis") or {}).model_dump()
    content = "\n".join(_line(m) for m in await run_in_threadpool(store.messages, conversation["id"]) if _line(m))
    transcript_id = await run_in_threadpool(store.save_transcript, conversation, content, analysis, consent_at or None)
    await run_in_threadpool(store.update, conversation["id"], {"agent_state": keep, "transcript_id": transcript_id})


async def _hold(store: Store, conversation: dict, text: str, reasons: list[str], messages: list[dict]) -> None:
    """Keeps an AI reply for the lawyer to approve, and tells the client a lawyer will reply (once)."""
    await run_in_threadpool(lambda: store.add_message(conversation["id"], "out", "ai", text, "text",
                                                      status="pending", hold_reasons=reasons))
    last_sent = next((m for m in reversed(messages) if m["sender"] != "client" and m.get("status", "sent") == "sent"), None)
    if not last_sent or last_sent["body"] != intake_guard.HOLDING_MESSAGE:
        await _reply(store, conversation, intake_guard.HOLDING_MESSAGE, "system")


async def settle_held_reply(conversation: dict, message_id: str, reviewer_id: str, *, send: bool,
                            text: str | None = None, db=None) -> dict:
    """The lawyer approves a held AI reply (as written, or edited) or discards it."""
    store = Store(db or get_supabase_admin())
    message = await run_in_threadpool(store.message, conversation["id"], message_id)
    if message is None or message["status"] != "pending":
        raise LookupError("No reply waiting for approval with that id")
    reviewed = {"reviewed_by": reviewer_id, "reviewed_at": _now()}
    if not send:
        if not await run_in_threadpool(store.review_message, message_id, {**reviewed, "status": "discarded"}):
            raise LookupError("This reply was already handled")
        return {**message, **reviewed, "status": "discarded"}
    body = (text or "").strip() or message["body"]
    # Claim it first so two lawyers approving at once can't both send it.
    if not await run_in_threadpool(store.review_message, message_id, {**reviewed, "status": "sent", "body": body,
                                                                      "sender": "lawyer" if body != message["body"] else "ai"}):
        raise LookupError("This reply was already handled")
    try:
        sent_id = await whatsapp_service.send_text(conversation["phone_number_id"], conversation["wa_id"], body)
    except whatsapp_service.WhatsAppError:
        await run_in_threadpool(lambda: store.db.table("whatsapp_messages").update({"status": "pending"}).eq("id", message_id).execute())
        raise
    if sent_id:
        await run_in_threadpool(lambda: store.db.table("whatsapp_messages").update({"wa_message_id": sent_id}).eq("id", message_id).execute())
    await run_in_threadpool(store.update, conversation["id"], {})
    return {**message, **reviewed, "status": "sent", "body": body}


async def reply_as_lawyer(conversation: dict, text: str, db=None) -> None:
    """A lawyer's message from the inbox; the AI stops replying in this chat."""
    store = Store(db or get_supabase_admin())
    sent_id = await whatsapp_service.send_text(conversation["phone_number_id"], conversation["wa_id"], text)
    await run_in_threadpool(store.add_message, conversation["id"], "out", "lawyer", text, "text", sent_id)
    await run_in_threadpool(store.update, conversation["id"], {"status": "lawyer"})

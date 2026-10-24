"""WhatsApp Cloud API (Meta): webhook verification, incoming messages, sending, voice notes.

  verify_subscription   the GET handshake when the webhook is registered (hub.verify_token)
  verify_signature      X-Hub-Signature-256 on every POST: HMAC-SHA256 of the raw body with the app secret
  parse_messages        the incoming messages in a webhook payload
  send_text / send_template / download_media / transcribe_voice_note

Free-form replies are only allowed within 24 hours of the client's last message; outside it
(e.g. hearing reminders) an approved template message is needed.
"""

import hashlib
import hmac
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

GRAPH = "https://graph.facebook.com"
MAX_TEXT = 4096


class WhatsAppError(RuntimeError):
    pass


def is_configured() -> bool:
    settings = get_settings()
    return bool(settings.whatsapp_access_token and settings.whatsapp_app_secret)


def verify_subscription(mode: str | None, token: str | None) -> bool:
    expected = get_settings().whatsapp_verify_token
    return mode == "subscribe" and bool(expected) and hmac.compare_digest(token or "", expected)


def verify_signature(body: bytes, header: str | None) -> bool:
    secret = get_settings().whatsapp_app_secret
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


@dataclass(frozen=True)
class Incoming:
    phone_number_id: str
    wa_id: str
    message_id: str
    kind: str  # text | audio | other
    text: str
    media_id: str | None = None
    name: str | None = None


def parse_messages(payload: dict) -> list[Incoming]:
    messages = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            number_id = (value.get("metadata") or {}).get("phone_number_id")
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
            for m in value.get("messages") or []:
                kind = m.get("type")
                if kind == "text":
                    messages.append(Incoming(number_id, m["from"], m["id"], "text", (m.get("text") or {}).get("body", ""), name=names.get(m["from"])))
                elif kind in ("audio", "voice"):
                    media = m.get("audio") or m.get("voice") or {}
                    messages.append(Incoming(number_id, m["from"], m["id"], "audio", "", media.get("id"), names.get(m["from"])))
                elif kind == "interactive":
                    reply = (m.get("interactive") or {}).get("button_reply") or {}
                    messages.append(Incoming(number_id, m["from"], m["id"], "text", reply.get("title", ""), name=names.get(m["from"])))
                else:
                    messages.append(Incoming(number_id, m["from"], m["id"], "other", "", name=names.get(m["from"])))
    return messages


def _headers() -> dict:
    token = get_settings().whatsapp_access_token
    if not token:
        raise WhatsAppError("WhatsApp is not configured (WHATSAPP_ACCESS_TOKEN)")
    return {"Authorization": f"Bearer {token}"}


async def _post(phone_number_id: str, body: dict, http_client: httpx.AsyncClient | None) -> str | None:
    url = f"{GRAPH}/{get_settings().whatsapp_graph_version}/{phone_number_id}/messages"
    client = http_client or httpx.AsyncClient(timeout=20)
    try:
        response = await client.post(url, headers=_headers(), json={"messaging_product": "whatsapp", **body})
    finally:
        if http_client is None:
            await client.aclose()
    if response.status_code >= 400:
        detail = (response.json().get("error") or {}).get("message", "") if response.content else ""
        raise WhatsAppError(f"WhatsApp send failed ({response.status_code}) {detail}".strip())
    return ((response.json().get("messages") or [{}])[0]).get("id")


async def send_text(phone_number_id: str, to: str, text: str, *, http_client: httpx.AsyncClient | None = None) -> str | None:
    """A free-form message (only within 24 hours of the client's last message)."""
    return await _post(phone_number_id, {"to": to, "type": "text", "text": {"body": text[:MAX_TEXT], "preview_url": False}}, http_client)


async def send_template(phone_number_id: str, to: str, template: str, parameters: list[str], *,
                        http_client: httpx.AsyncClient | None = None) -> str | None:
    """An approved template message (any time), e.g. a hearing reminder."""
    settings = get_settings()
    body = {
        "to": to,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": settings.whatsapp_template_language},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": p[:1000]} for p in parameters]}],
        },
    }
    return await _post(phone_number_id, body, http_client)


async def download_media(media_id: str, *, http_client: httpx.AsyncClient | None = None) -> bytes:
    client = http_client or httpx.AsyncClient(timeout=60)
    try:
        meta = await client.get(f"{GRAPH}/{get_settings().whatsapp_graph_version}/{media_id}", headers=_headers())
        if meta.status_code >= 400:
            raise WhatsAppError(f"Media lookup failed ({meta.status_code})")
        media = await client.get(meta.json()["url"], headers=_headers())
        if media.status_code >= 400:
            raise WhatsAppError(f"Media download failed ({media.status_code})")
        return media.content
    finally:
        if http_client is None:
            await client.aclose()


async def transcribe_voice_note(audio: bytes) -> str:
    """A voice note as text; `multi` lets Nova-3 follow Hindi-English code-switching."""
    from deepgram import AsyncDeepgramClient

    settings = get_settings()
    if not settings.deepgram_api_key:
        raise WhatsAppError("Voice notes need DEEPGRAM_API_KEY")
    response = await AsyncDeepgramClient(api_key=settings.deepgram_api_key).listen.v1.media.transcribe_file(
        request=audio, model=settings.deepgram_model, language="multi", smart_format=True, punctuate=True,
    )
    channels = getattr(response.results, "channels", None) or []
    alternatives = channels[0].alternatives if channels else []
    return (alternatives[0].transcript if alternatives else "").strip()


def to_e164(wa_id: str) -> str:
    return "+" + wa_id.lstrip("+")


def to_wa_id(phone: str) -> str:
    return phone.lstrip("+")

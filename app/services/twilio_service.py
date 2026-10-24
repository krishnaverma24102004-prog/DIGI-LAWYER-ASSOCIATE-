"""Twilio phone intake: TwiML, request verification, stream tokens and G.711 audio.

A call to one of the firm's Twilio numbers goes:

  Twilio --POST /telephony/voice/incoming--> verify X-Twilio-Signature, find the number's
         organization, answer with <Connect><Stream> to wss://.../ws/telephony carrying a
         short-lived signed token (Twilio Media Streams can't send auth headers)
  Twilio --WebSocket /ws/telephony--> 8 kHz G.711 mu-law frames, base64 in JSON "media"
         events; decoded to 16-bit PCM for Deepgram; the AI's replies come back from
         Deepgram Aura as 8 kHz PCM, are encoded to mu-law and sent as "media" events

Audio conversion is plain G.711 (ITU-T) mu-law, vectorized with numpy.
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import numpy as np
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Connect, Hangup, Say, VoiceResponse

from app.core.config import get_settings

SAMPLE_RATE = 8000
FRAME_BYTES = 160  # 20 ms of 8 kHz mu-law, the frame size Twilio sends and expects

# ----------------------------------------------------------------------------- G.711 mu-law

_BIAS = 0x84
# Encoder constants of the reference implementation (Sun g711.c, as in CPython's audioop).
_ENC_BIAS = 0x21
_ENC_CLIP = 8159
_SEG_END = np.array([0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF])


def _build_decode_table() -> np.ndarray:
    u = ~np.arange(256, dtype=np.int32) & 0xFF
    sign = u & 0x80
    exponent = (u >> 4) & 0x07
    mantissa = u & 0x0F
    magnitude = (((mantissa << 3) + _BIAS) << exponent) - _BIAS
    return np.where(sign != 0, -magnitude, magnitude).astype(np.int16)


_DECODE = _build_decode_table()


def mulaw_to_pcm16(data: bytes) -> bytes:
    """mu-law bytes -> little-endian 16-bit PCM (same sample rate)."""
    return _DECODE[np.frombuffer(data, dtype=np.uint8)].astype("<i2").tobytes()


def pcm16_to_mulaw(data: bytes) -> bytes:
    """Little-endian 16-bit PCM -> mu-law bytes (same sample rate)."""
    samples = np.frombuffer(data[: len(data) - len(data) % 2], dtype="<i2").astype(np.int32) >> 2  # to 14 bits
    mask = np.where(samples < 0, 0x7F, 0xFF)
    magnitude = np.minimum(np.abs(samples), _ENC_CLIP) + _ENC_BIAS
    segment = np.searchsorted(_SEG_END, magnitude)  # first segment whose end >= magnitude
    value = np.where(segment >= 8, 0x7F, (segment << 4) | ((magnitude >> (segment + 1)) & 0x0F))  # >= 8: clipped
    return ((value ^ mask) & 0xFF).astype(np.uint8).tobytes()


def frames(mulaw: bytes, size: int = FRAME_BYTES) -> list[bytes]:
    return [mulaw[i : i + size] for i in range(0, len(mulaw), size)]


# ----------------------------------------------------------------------------- Media Stream messages


def media_message(stream_sid: str, mulaw: bytes) -> str:
    return json.dumps({"event": "media", "streamSid": stream_sid, "media": {"payload": base64.b64encode(mulaw).decode()}})


def clear_message(stream_sid: str) -> str:
    """Tells Twilio to drop audio it has buffered but not yet played (barge-in)."""
    return json.dumps({"event": "clear", "streamSid": stream_sid})


def mark_message(stream_sid: str, name: str) -> str:
    return json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": name}})


# ----------------------------------------------------------------------------- request verification


class TelephonyNotConfigured(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(get_settings().twilio_auth_token)


def _auth_token() -> str:
    token = get_settings().twilio_auth_token
    if not token:
        raise TelephonyNotConfigured("TWILIO_AUTH_TOKEN is not set")
    return token


def public_url(path: str, query: str = "", *, scheme: str = "https") -> str | None:
    """The URL Twilio used (signature checks need it exactly), from PUBLIC_BASE_URL."""
    base = get_settings().public_base_url.rstrip("/")
    if not base:
        return None
    if scheme == "wss":
        base = "wss://" + base.split("://", 1)[-1]
    return f"{base}{path}" + (f"?{query}" if query else "")


def verify_signature(url: str, params: dict, signature: str | None) -> bool:
    if not signature:
        return False
    return RequestValidator(_auth_token()).validate(url, params, signature)


# ----------------------------------------------------------------------------- stream tokens


@dataclass(frozen=True)
class StreamClaims:
    call_sid: str
    phone_number: str


def _sign(body: str) -> str:
    key = hashlib.sha256(b"telephony-stream:" + _auth_token().encode()).digest()
    return base64.urlsafe_b64encode(hmac.new(key, body.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def create_stream_token(call_sid: str, phone_number: str, ttl_seconds: int | None = None) -> str:
    ttl = ttl_seconds or get_settings().telephony_stream_token_seconds
    body = base64.urlsafe_b64encode(
        json.dumps({"c": call_sid, "n": phone_number, "e": int(time.time()) + ttl}).encode()
    ).decode().rstrip("=")
    return f"{body}.{_sign(body)}"


def verify_stream_token(token: str | None) -> StreamClaims | None:
    """The call a stream token was issued for, or None if forged or expired."""
    if not token or token.count(".") != 1:
        return None
    body, signature = token.split(".")
    if not hmac.compare_digest(signature, _sign(body)):
        return None
    try:
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    if claims.get("e", 0) < time.time():
        return None
    return StreamClaims(call_sid=claims["c"], phone_number=claims["n"])


# ----------------------------------------------------------------------------- TwiML


def connect_stream_twiml(stream_url: str, token: str, caller: str | None = None) -> str:
    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=stream_url)
    stream.parameter(name="token", value=token)
    if caller:
        stream.parameter(name="caller", value=caller)
    response.append(connect)
    return str(response)


def unavailable_twiml(message: str = "Sorry, this line is not available right now. Please call back later.") -> str:
    response = VoiceResponse()
    response.append(Say(message))
    response.append(Hangup())
    return str(response)


def find_number(phone_number: str, db=None) -> dict | None:
    """The enabled number's configuration. Service role: a call has no user. Blocking."""
    from app.database import get_supabase_admin

    db = db or get_supabase_admin()
    rows = (
        db.table("telephony_numbers").select("*").eq("phone_number", phone_number).eq("enabled", True)
        .limit(1).execute().data
    )
    return rows[0] if rows else None

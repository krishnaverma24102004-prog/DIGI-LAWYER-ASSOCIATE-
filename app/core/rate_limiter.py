"""Rate limiting (slowapi).

Two layers:

* a default limit on every /api/ HTTP route (RATE_LIMIT_DEFAULT), applied by
  `RateLimitMiddleware`; provider webhooks are exempt (Twilio, Stripe and Meta send from shared
  IP ranges and authenticate by signature), as are health checks and metrics outside /api/;
* stricter named limits on expensive routes, as dependencies: `limit("llm")` on the
  endpoints that call Claude, Deepgram or Tavily, `limit("billing")` on billing.

Clients are keyed by their bearer token (hashed, so a forged user id can't use up someone
else's quota) or, without one, by IP address. Counters live in Redis when REDIS_URL is set,
so every API replica shares them; otherwise in process memory.
"""

import asyncio
import hashlib
import math
import time

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings


def client_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return "token:" + hashlib.sha256(token.strip().encode()).hexdigest()[:32]
    return "ip:" + get_remote_address(request)


def _build_limiter() -> Limiter:
    settings = get_settings()
    return Limiter(
        key_func=client_key,
        storage_uri=settings.redis_url or "memory://",
        enabled=settings.rate_limit_enabled,
        # Keep serving (with per-process counters) if Redis is briefly unreachable.
        in_memory_fallback_enabled=bool(settings.redis_url),
        headers_enabled=False,
    )


limiter = _build_limiter()

_RATES = {"llm": "rate_limit_llm", "billing": "rate_limit_billing"}
EXEMPT_PATHS = {"/api/v1/billing/webhook", "/api/v1/telephony/voice/incoming", "/api/v1/whatsapp/webhook"}


def _retry_after(item, scope: str, key: str) -> int:
    reset_at, _ = limiter.limiter.get_window_stats(item, scope, key)
    return max(1, math.ceil(reset_at - time.time()))


def _hit(item, scope: str, key: str) -> int | None:
    """Count one request; None if allowed, else seconds until the window resets."""
    return None if limiter.limiter.hit(item, scope, key) else _retry_after(item, scope, key)


class RateLimitMiddleware:
    """RATE_LIMIT_DEFAULT per client on every /api/ HTTP request (WebSockets pass through)."""

    def __init__(self, app: ASGIApp):
        self.app = app
        rate = get_settings().rate_limit_default
        self.rate = rate
        self.item = parse(rate) if rate else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if (scope["type"] != "http" or self.item is None or not limiter.enabled
                or not path.startswith("/api/") or path in EXEMPT_PATHS):
            return await self.app(scope, receive, send)
        key = client_key(Request(scope))
        if get_settings().redis_url:  # network I/O: keep it off the event loop
            retry_after = await asyncio.to_thread(_hit, self.item, "default", key)
        else:
            retry_after = _hit(self.item, "default", key)
        if retry_after is None:
            return await self.app(scope, receive, send)
        response = JSONResponse(
            {"detail": f"Rate limit exceeded ({self.rate}); try again in {retry_after} s"},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)


def limit(scope: str):
    """Dependency enforcing the named limit (RATE_LIMIT_<SCOPE>) per client."""
    rate = getattr(get_settings(), _RATES[scope])
    item = parse(rate)

    def dependency(request: Request) -> None:  # sync: FastAPI runs it in a worker thread (Redis I/O)
        if not limiter.enabled:
            return
        retry_after = _hit(item, scope, key=client_key(request))
        if retry_after is None:
            return
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Rate limit exceeded ({rate}); try again in {retry_after} s",
            headers={"Retry-After": str(retry_after)},
        )

    return dependency

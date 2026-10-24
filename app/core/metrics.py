"""Prometheus metrics beyond the per-route HTTP metrics of prometheus-fastapi-instrumentator.

* Claude token consumption, by model and kind (input, output, cache read, cache write)
* phone calls: active calls, calls handled, and response latency (from the caller's
  finished sentence to the first audio of the AI's reply)
* live audio sessions open, by transport
* open database connections, sampled in the background (see `refresh_db_connections`)

All are exposed at /metrics (app/main.py).
"""

import logging

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

CLAUDE_TOKENS = Counter(
    "claude_tokens_total", "Tokens consumed by Claude API calls", ["model", "kind"]
)
CLAUDE_REQUESTS = Counter("claude_requests_total", "Claude API responses received", ["model", "stop_reason"])

TELEPHONY_CALLS = Counter("telephony_calls_total", "Phone calls handled", ["outcome"])
TELEPHONY_ACTIVE_CALLS = Gauge("telephony_active_calls", "Phone calls currently connected")
TELEPHONY_RESPONSE_LATENCY = Histogram(
    "telephony_response_latency_seconds",
    "From the caller's finished sentence to the first audio of the AI's spoken reply",
    buckets=(0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 20),
)

LIVE_SESSIONS_ACTIVE = Gauge("live_sessions_active", "Live consultation sessions in progress", ["transport"])

DB_CONNECTIONS = Gauge("db_connections_open", "Open connections to the Supabase Postgres database")

_USAGE_FIELDS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
}


def record_claude_usage(response) -> None:
    """Count the tokens of one Messages API response. Never raises."""
    try:
        model = getattr(response, "model", None) or "unknown"
        CLAUDE_REQUESTS.labels(model=model, stop_reason=str(getattr(response, "stop_reason", None))).inc()
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        for field, kind in _USAGE_FIELDS.items():
            value = getattr(usage, field, None)
            if isinstance(value, int) and value > 0:
                CLAUDE_TOKENS.labels(model=model, kind=kind).inc(value)
    except Exception:  # metrics must never break a request
        logger.debug("Recording Claude usage failed", exc_info=True)


def refresh_db_connections() -> None:
    """Sample open DB connections via public.db_connection_count() (service role). Blocking."""
    from app.database import get_supabase_admin

    count = get_supabase_admin().rpc("db_connection_count", {}).execute().data
    DB_CONNECTIONS.set(int(count))

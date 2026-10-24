import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.core import guardrails, metrics
from app.core.config import get_settings
from app.core.rate_limiter import RateLimitMiddleware
from app.routers import (
    audio_stream,
    billing,
    case_threads,
    caselaw,
    cases,
    documents,
    drafting,
    evidence,
    health,
    jobs,
    knowledge,
    organizations,
    practice_areas,
    public_config,
    reviews,
    safety,
    telephony,
    transcripts,
    webhooks,
    webrtc,
    whatsapp,
    workflows,
)
from app.services import anthropic_service, queue_service, rag_service, tts_service

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

settings = get_settings()


async def _warm_up_embeddings() -> None:
    # The first load downloads the model (~200 MB) once; do it before the first consultation needs it.
    try:
        await asyncio.to_thread(rag_service.get_embedder().warm_up)
        logger.info("Embedding model ready")
    except Exception:
        logger.exception("Embedding model warm-up failed; RAG will retry on first use")


async def _warm_up_pii_masking() -> None:
    # Loading spaCy takes a second or two; do it before the first transcript arrives.
    try:
        await asyncio.to_thread(guardrails.warm_up)
        logger.info("PII masking ready")
    except Exception:
        logger.exception("PII masking warm-up failed; live AI analysis will stop if masking is unavailable")


async def _sample_db_connections() -> None:
    # Periodic, so a /metrics scrape never waits on (or hammers) the database.
    while True:
        try:
            await asyncio.to_thread(metrics.refresh_db_connections)
        except Exception as exc:
            logger.debug("DB connection gauge not updated: %s", exc)
        await asyncio.sleep(settings.db_metrics_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Clients must never be served by a local test model: refuse to start instead.
    if problems := anthropic_service.production_model_problems():
        raise RuntimeError("Refusing to start in production with a test model: " + "; ".join(problems))
    tasks = []
    if settings.metrics_enabled and settings.supabase_url and settings.supabase_service_role_key:
        tasks.append(asyncio.create_task(_sample_db_connections()))
    if settings.rag_enabled and settings.embedding_warmup:
        tasks.append(asyncio.create_task(_warm_up_embeddings()))
    if settings.pii_masking_enabled:
        tasks.append(asyncio.create_task(_warm_up_pii_masking()))
    yield
    for task in tasks:
        if not task.done():
            task.cancel()
    await webrtc.close_all()
    await anthropic_service.close_client()
    await tts_service.close_client()
    await queue_service.close_pool()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Default per-client limit on every /api/ HTTP route; see core/rate_limiter.py.
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Lets the browser app read download file names (PDF reports, .docx drafts).
    expose_headers=["Content-Disposition"],
)

app.include_router(health.router)
app.include_router(public_config.router, prefix="/api/v1")
app.include_router(transcripts.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(organizations.router, prefix="/api/v1")
app.include_router(practice_areas.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(case_threads.router, prefix="/api/v1")
app.include_router(evidence.router, prefix="/api/v1")
app.include_router(drafting.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
app.include_router(audio_stream.router, prefix="/api/v1")
app.include_router(webrtc.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(telephony.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(reviews.router, prefix="/api/v1")
app.include_router(workflows.router, prefix="/api/v1")
app.include_router(cases.router, prefix="/api/v1")
app.include_router(whatsapp.router, prefix="/api/v1")
app.include_router(caselaw.router, prefix="/api/v1")
app.include_router(safety.router, prefix="/api/v1")


def _metrics_auth(request: Request) -> None:
    if settings.metrics_token:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied, settings.metrics_token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Metrics token required")


if settings.metrics_enabled:
    Instrumentator(excluded_handlers=["/metrics", "/health", "/health/db"]).instrument(app).expose(
        app, include_in_schema=False, dependencies=[Depends(_metrics_auth)]
    )

# Mounted last: "/" catches every path the routers above don't handle.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

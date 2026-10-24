"""Background jobs on Redis (ARQ): enqueue from the API, run in `app/worker.py`.

Jobs that carry a `user_id` keyword argument belong to that user: `get_job` only reveals
them to the same user. Without REDIS_URL, `is_configured()` is False and callers use their
synchronous fallbacks.
"""

import asyncio
import logging
from dataclasses import dataclass

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobStatus

from app.core.config import get_settings

logger = logging.getLogger(__name__)

QUEUE_NAME = "digi-lawyer:jobs"

_pool: ArqRedis | None = None
_pool_lock = asyncio.Lock()


class QueueNotConfigured(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(get_settings().redis_url)


def redis_settings() -> RedisSettings:
    url = get_settings().redis_url
    if not url:
        raise QueueNotConfigured("REDIS_URL is not set")
    return RedisSettings.from_dsn(url)


async def get_pool() -> ArqRedis:
    global _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await create_pool(redis_settings(), default_queue_name=QUEUE_NAME)
        return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue(function: str, *args, **kwargs) -> str:
    """Queue `function` (a task in app/worker.py); returns the job id."""
    pool = await get_pool()
    job = await pool.enqueue_job(function, *args, _queue_name=QUEUE_NAME, **kwargs)
    if job is None:  # only when a job with the same _job_id is already queued
        raise RuntimeError(f"Job for {function} is already queued")
    logger.info("Queued %s as job %s", function, job.job_id)
    return job.job_id


@dataclass
class JobInfo:
    job_id: str
    function: str
    status: str  # queued, in_progress, complete, failed, not_found
    result: object = None
    error: str | None = None


async def get_job(job_id: str, user_id: str) -> JobInfo | None:
    """A job's status and result, or None if it doesn't exist or isn't this user's."""
    pool = await get_pool()
    job = Job(job_id, pool, _queue_name=QUEUE_NAME)
    status = await job.status()
    if status == JobStatus.not_found:
        return None
    if status == JobStatus.complete:
        info = await job.result_info()
        if info is None or info.kwargs.get("user_id") != user_id:
            return None
        if info.success:
            return JobInfo(job_id, info.function, "complete", result=info.result)
        # Don't leak worker internals; the worker log has the traceback.
        return JobInfo(job_id, info.function, "failed", error=type(info.result).__name__)
    info = await job.info()
    if info is None or info.kwargs.get("user_id") != user_id:
        return None
    return JobInfo(job_id, info.function, "in_progress" if status == JobStatus.in_progress else "queued")

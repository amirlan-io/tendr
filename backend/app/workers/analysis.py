"""Redis worker for durable tender-analysis jobs.

Run as a separate process:
    python -m app.workers.analysis
"""

from __future__ import annotations

import asyncio

from loguru import logger
from redis.asyncio import Redis

from app.core.config import get_settings
from app.services.analysis_jobs import run_analysis_job


async def serve() -> None:
    settings = get_settings()
    if settings.analysis_job_mode != "redis":
        raise RuntimeError("ANALYSIS_JOB_MODE must be 'redis' for the worker")
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    logger.info("Analysis worker listening on {}", settings.analysis_job_queue_name)
    try:
        while True:
            item = await client.blpop(settings.analysis_job_queue_name, timeout=10)
            if not item:
                continue
            _queue, job_id = item
            try:
                await run_analysis_job(str(job_id))
            except asyncio.CancelledError:
                await client.lpush(settings.analysis_job_queue_name, str(job_id))
                raise
            except Exception as exc:  # final guard; run_analysis_job records failures
                logger.exception("Analysis worker failed for {}: {}", job_id, exc)
    finally:
        await client.aclose()


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()

"""Acknowledged Redis Stream queue with database leases and periodic reconciliation."""
from __future__ import annotations
import asyncio
import secrets
from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import ResponseError, ConnectionError, TimeoutError
from app.core.config import get_settings
from app.services.analysis_jobs import run_analysis_job, recover_analysis_jobs

async def reconcile():
    while True:
        try:
            await recover_analysis_jobs()
        except Exception:
            logger.exception("Job reconciliation failed; will retry")
        await asyncio.sleep(15)

async def serve() -> None:
    settings = get_settings()
    if settings.analysis_job_mode != "redis":
        raise RuntimeError("ANALYSIS_JOB_MODE must be 'redis'")
    client = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=15, socket_connect_timeout=5)
    stream, group, consumer = settings.analysis_job_queue_name + ":stream", "analysis", secrets.token_hex(8)
    try:
        await client.xgroup_create(stream, group, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc): raise
    recovery = asyncio.create_task(reconcile())
    try:
        while True:
            try:
                reclaimed = await client.xautoclaim(stream, group, consumer, min_idle_time=150000, start_id="0-0", count=1)
                entries = reclaimed[1]
                if not entries:
                    batches = await client.xreadgroup(group, consumer, {stream: ">"}, count=1, block=5000)
                    entries = batches[0][1] if batches else []
            except (ConnectionError, TimeoutError):
                logger.warning("Redis temporarily unavailable; retrying unacknowledged queue")
                await asyncio.sleep(1)
                continue
            for message_id, fields in entries:
                try:
                    await run_analysis_job(fields["job_id"])
                except asyncio.CancelledError:
                    raise  # unacknowledged entry is claimed by another worker later
                except Exception as exc:
                    logger.exception("Worker failed: {}", exc)
                    continue
                await client.xack(stream, group, message_id)
                await client.xdel(stream, message_id)
    finally:
        recovery.cancel()
        await asyncio.gather(recovery, return_exceptions=True)
        await client.aclose()

def main(): asyncio.run(serve())
if __name__ == "__main__": main()

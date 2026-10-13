"""Persistent background jobs for long-running tender analyses.

The job row is the source of truth for the UI.  A browser refresh therefore
does not cancel the analysis or lose its result.  In-progress jobs are queued
again on application startup, which also makes a normal backend restart safe.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from pathlib import Path

from loguru import logger
from sqlalchemy import select, update, or_

from app.core.config import get_settings
from app.db import SessionLocal
from app.db import repo as db_repo
from app.db.models import AnalysisJob, User
from app.schemas.lot import LotCreate
from app.services.orchestrator import LotOrchestrator, analyze_uploaded_file


_tasks: set[asyncio.Task[None]] = set()


def analysis_job_storage_dir() -> Path:
    configured = get_settings().analysis_job_storage_dir.strip()
    root = Path(configured) if configured else Path(tempfile.gettempdir()) / "tendr-analysis-jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


async def schedule_analysis_job(job_id: str) -> None:
    """Run locally in development or enqueue for a dedicated Redis worker."""
    settings = get_settings()
    if settings.analysis_job_mode == "redis":
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            await client.eval(
                "if redis.call('SET', KEYS[1], '1', 'NX', 'EX', 30) then return redis.call('XADD', KEYS[2], '*', 'job_id', ARGV[1]) end return nil",
                2, f"tendr:analysis:enqueued:{job_id}", settings.analysis_job_queue_name + ":stream", job_id,
            )
        finally:
            await client.aclose()
        return

    task = asyncio.create_task(run_analysis_job(job_id), name=f"analysis-job-{job_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def shutdown_analysis_jobs() -> None:
    """Stop local runners without deleting their durable job rows."""
    tasks = list(_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def recover_analysis_jobs() -> None:
    """Requeue unfinished jobs after a backend restart."""
    try:
        async with SessionLocal() as session:
            await session.execute(
                update(AnalysisJob)
                .where(AnalysisJob.status == "running", or_(AnalysisJob.lease_until.is_(None), AnalysisJob.lease_until < datetime.now(UTC).replace(tzinfo=None)))
                .values(status="queued", lease_owner=None, lease_until=None, progress=5, stage="Возобновляем анализ")
            )
            rows = await session.execute(
                select(AnalysisJob).where(AnalysisJob.status == "queued")
            )
            jobs = list(rows.scalars().all())
            resumable: list[str] = []
            for job in jobs:
                if job.attempts >= 3:
                    job.status = "failed"
                    job.error_code = "RETRY_LIMIT_REACHED"
                    if job.reservation_key:
                        await db_repo.release_user_quota(session, job.user_id, reservation_key=job.reservation_key)
                    continue
                if job.kind == "upload":
                    path = str((job.input_json or {}).get("path") or "")
                    if not path or not os.path.isfile(path):
                        job.status = "failed"
                        job.error_code = "UPLOAD_EXPIRED"
                        job.stage = "Загруженный файл больше недоступен"
                        job.completed_at = datetime.now(UTC).replace(tzinfo=None)
                        if job.reservation_key:
                            await db_repo.release_user_quota(
                                session,
                                job.user_id,
                                reservation_key=job.reservation_key,
                            )
                        continue
                resumable.append(job.id)
            await session.commit()
        for job_id in resumable:
            await schedule_analysis_job(job_id)
    except Exception as exc:  # missing migration must not make the whole API unavailable
        logger.warning("Could not recover analysis jobs: {}", exc)


async def _set_progress(job_id: str, progress: int, stage: str) -> None:
    async with SessionLocal() as session:
        job = await session.get(AnalysisJob, job_id)
        if job and job.status == "running":
            job.progress = max(0, min(99, progress))
            job.stage = stage[:160]
            await session.commit()


async def run_analysis_job(job_id: str) -> None:
    input_data: dict = {}
    user_id: int | None = None
    reservation_key: str | None = None
    kind = "url"
    cleanup_upload = True

    owner = uuid4().hex
    heartbeat = None
    # Claim exactly once. Two web workers may both see the same queued row.
    async with SessionLocal() as session:
        claimed = await session.execute(
            update(AnalysisJob)
            .where(AnalysisJob.id == job_id, AnalysisJob.status == "queued")
            .values(status="running", lease_owner=owner, lease_until=datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=120), attempts=AnalysisJob.attempts + 1, progress=8, stage="Получаем данные закупки")
        )
        await session.commit()
        if not claimed.rowcount:
            return
        job = await session.get(AnalysisJob, job_id)
        if not job:
            return
        input_data = dict(job.input_json or {})
        user_id = job.user_id
        reservation_key = job.reservation_key
        kind = job.kind

    heartbeat = asyncio.create_task(_heartbeat(job_id, owner))
    try:
        await _set_progress(job_id, 18, "Читаем документы и техническое задание")
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise LookupError("analysis job user not found")
            quota = await db_repo.get_user_quota(session, user.id)
            free_limit = int(quota.get("monthly_limit") or quota.get("limit") or 3)
            used = int(quota.get("used_this_month") or quota.get("used") or 0)

            if kind == "upload":
                path = str(input_data.get("path") or "")
                if not path or not os.path.isfile(path):
                    raise FileNotFoundError("stored upload is missing")
                result = await analyze_uploaded_file(
                    path,
                    user_id=user.id,
                    is_pilot=bool(quota.get("is_pilot", False)),
                    used_this_month=used,
                    free_limit=free_limit,
                    session=session,
                )
                source_url = f"upload:{input_data.get('filename') or 'document'}"
            else:
                url = str(input_data.get("url") or "")
                source_id = str(input_data.get("source_id") or "0")
                result = await LotOrchestrator(session=session).analyze_lot(
                    LotCreate(source_url=url, source_id=source_id),
                    user_id=user.id,
                    is_pilot=bool(quota.get("is_pilot", False)),
                    used_this_month=used,
                    free_limit=free_limit,
                )
                source_url = url

            # Keep this update in the same transaction as the analysis.  A second
            # writer here can deadlock SQLite while the analyzer has pending data.
            owned = await session.scalar(select(AnalysisJob).where(
                AnalysisJob.id == job_id, AnalysisJob.lease_owner == owner,
                AnalysisJob.status == "running",
            ).with_for_update())
            if owned is None:
                cleanup_upload = False
                await session.rollback()
                return
            job = owned
            job.progress = 82
            job.stage = "Собираем риски и итоговый план"
            payload = result.model_dump(mode="json")
            analysis = None
            if result.lot and result.lot.lot_id:
                analysis = await db_repo.push_history(
                    session,
                    user.id,
                    {
                        "lot_id": result.lot.lot_id,
                        "title": result.lot.title,
                        "url": source_url,
                        "overall_risk": result.legal.overall_risk if result.legal else "needs_review",
                        "n_requirements": len(result.lot.requirements or []),
                        "n_red_flags": len(result.lot.red_flags or []),
                        "result_json": payload,
                    },
                )
            if reservation_key and not result.incomplete:
                await db_repo.confirm_user_quota(
                    session, user.id, reservation_key=reservation_key
                )
            if reservation_key and result.incomplete:
                await db_repo.release_user_quota(session, user.id, reservation_key=reservation_key)
            job = job or await session.get(AnalysisJob, job_id)
            if job:
                job.status = "completed"
                job.progress = 100
                job.stage = (
                    "Анализ завершён частично — проверьте исходные данные"
                    if result.incomplete
                    else "Анализ готов"
                )
                job.result_json = payload
                job.analysis_id = analysis.id if analysis else None
                job.completed_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
    except asyncio.CancelledError:
        # Preserve an uploaded source so the row can be requeued during startup.
        cleanup_upload = False
        async with SessionLocal() as session:
            await session.execute(update(AnalysisJob).where(
                AnalysisJob.id == job_id, AnalysisJob.lease_owner == owner,
                AnalysisJob.status == "running",
            ).values(status="queued", lease_owner=None, lease_until=None))
            await session.commit()
        raise
    except Exception as exc:
        logger.exception("Analysis job {} failed: {}", job_id, exc)
        async with SessionLocal() as session:
            job = await session.get(AnalysisJob, job_id)
            if job and job.lease_owner == owner:
                if reservation_key and user_id is not None:
                    await db_repo.release_user_quota(
                        session,
                        user_id,
                        reservation_key=reservation_key,
                    )
                job.status = "failed"
                job.progress = 100
                job.error_code = (
                    "UPLOAD_EXPIRED" if isinstance(exc, FileNotFoundError) else "ANALYSIS_FAILED"
                )
                job.stage = "Не удалось завершить анализ"
                job.completed_at = datetime.now(UTC).replace(tzinfo=None)
                await session.commit()
            else:
                cleanup_upload = False
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        if kind == "upload" and cleanup_upload:
            path = str(input_data.get("path") or "")
            if path:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    logger.warning("Could not remove analysis upload {}: {}", path, exc)


async def _heartbeat(job_id: str, owner: str) -> None:
    while True:
        await asyncio.sleep(15)
        async with SessionLocal() as session:
            result = await session.execute(update(AnalysisJob).where(
                AnalysisJob.id == job_id, AnalysisJob.status == "running", AnalysisJob.lease_owner == owner,
            ).values(lease_until=datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=120)))
            await session.commit()
            if not result.rowcount:
                return

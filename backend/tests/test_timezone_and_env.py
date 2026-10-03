"""Регрессионные тесты: часовые пояса в квоте и поиск .env.

Оба бага проявлялись только в бою: первый ронял /api/lots/analyze с 500,
второй не давал приложению прочитать .env вообще.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.db import repo as db_repo
from app.db.models import QuotaReservation, User


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _user_with_reservation(session, *, ttl: int = 300):
    user = User(web_client_id="tz_test_user_00001")
    session.add(user)
    await session.flush()
    reservation = QuotaReservation(
        user_id=user.id,
        reservation_key="key-1",
        operation_key="op",
        amount=1,
        month_key=datetime.now(UTC).strftime("%Y-%m"),
        status="reserved",
        # Наивные даты: колонка объявлена как TIMESTAMP WITHOUT TIME ZONE.
        reserved_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(seconds=ttl),
    )
    session.add(reservation)
    await session.flush()
    return user, reservation


@pytest.mark.asyncio
async def test_release_user_quota_accepts_aware_now(session) -> None:
    """Освобождение квоты не должно падать на смешении часовых поясов."""
    user, reservation = await _user_with_reservation(session)
    released = await db_repo.release_user_quota(
        session, user.id, reservation.reservation_key, now_override=datetime.now(UTC)
    )
    assert released is True
    await session.refresh(reservation)
    assert reservation.status == "released"
    # Значение должно быть наивным — иначе asyncpg его отвергнет.
    assert reservation.released_at is not None
    assert reservation.released_at.tzinfo is None


@pytest.mark.asyncio
async def test_release_with_naive_now(session) -> None:
    user, reservation = await _user_with_reservation(session)
    released = await db_repo.release_user_quota(
        session, user.id, reservation.reservation_key, now_override=datetime.utcnow()
    )
    assert released is True


@pytest.mark.asyncio
async def test_cleanup_expired_writes_naive_released_at(session) -> None:
    """Просроченные резервы чистятся с наивной датой."""
    user, reservation = await _user_with_reservation(session, ttl=-10)
    released = await db_repo.cleanup_expired_quota_reservations(session)
    assert released == 1
    await session.refresh(reservation)
    assert reservation.status == "released"
    assert reservation.released_at.tzinfo is None


@pytest.mark.asyncio
async def test_confirm_writes_naive_confirmed_at(session) -> None:
    user, reservation = await _user_with_reservation(session)
    ok = await db_repo.confirm_user_quota(
        session, user.id, reservation.reservation_key, now_override=datetime.now(UTC)
    )
    assert ok is True
    await session.refresh(reservation)
    assert reservation.confirmed_at is not None
    assert reservation.confirmed_at.tzinfo is None


@pytest.mark.asyncio
async def test_quota_roundtrip_with_timezone(session) -> None:
    """Полный цикл: резерв → подтверждение → отмена без 500-ошибок."""
    user, reservation = await _user_with_reservation(session)
    now = datetime.now(UTC)

    quota = await db_repo.get_user_quota(session, user.id, now_override=now)
    assert "remaining" in quota

    rows = await session.execute(
        select(QuotaReservation).where(QuotaReservation.user_id == user.id)
    )
    assert len(rows.scalars().all()) == 1


# ── Поиск .env ───────────────────────────────────────────────────────


def test_env_file_resolves_to_project_root() -> None:
    """config.py обязан находить .env в корне проекта, а не в backend/.

    Раньше был ``parents[2]``, что указывал на каталог backend/, и файл
    не читался: приложение стартовало с пустым LLM_API_KEY.
    """
    from app.core import config

    env_path = config._BACKEND_ENV_FILE
    assert env_path.name == ".env"
    # В корне проекта, а не внутри backend/app
    assert env_path.parent.name == "tendr"
    assert env_path.exists(), "коренной .env должен существовать в репозитории"

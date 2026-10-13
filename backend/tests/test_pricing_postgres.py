"""Opt-in verification of the per-account reservation lock on real PostgreSQL."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.core.config import get_settings
from app.db import repo
from app.db.models import User, Subscription, QuotaReservation


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("TENDR_TEST_POSTGRES") != "1",
    reason="Requires local PostgreSQL migrated to head",
)
async def test_parallel_reservations_cannot_exceed_plus_allowance():
    url = get_settings().database_url
    assert url.startswith("postgresql+asyncpg://")
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = None
    try:
        async with factory() as session:
            user = User(web_client_id="pricing_test_" + uuid4().hex)
            session.add(user)
            await session.flush()
            user_id = user.id
            now = datetime.now(UTC).replace(tzinfo=None)
            session.add(
                Subscription(
                    user_id=user_id,
                    plan="plus",
                    monthly_limit=0,
                    is_active=True,
                    starts_at=now - timedelta(hours=1),
                    expires_at=now + timedelta(days=1),
                )
            )
            await session.commit()

        async def reserve(index):
            async with factory() as session:
                try:
                    await repo.reserve_user_quota(
                        session, user_id, operation_key=f"parallel:{index}"
                    )
                    await session.commit()
                    return True
                except repo.QuotaLimitExceeded:
                    await session.rollback()
                    return False

        results = await asyncio.gather(*(reserve(i) for i in range(12)))
        assert sum(results) == 5
        async with factory() as session:
            quota = await repo.get_user_quota(session, user_id)
            assert quota["reserved"] == 5 and quota["remaining"] == 0
    finally:
        if user_id is not None:
            async with factory() as session:
                await session.execute(
                    delete(QuotaReservation).where(QuotaReservation.user_id == user_id)
                )
                await session.execute(delete(Subscription).where(Subscription.user_id == user_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
        await engine.dispose()

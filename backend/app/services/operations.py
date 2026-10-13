"""One billing boundary for all externally billed operations."""
from contextlib import asynccontextmanager
from functools import wraps
import inspect
import uuid

from fastapi import HTTPException
from app.core.client_id import require_authenticated_client_id
from app.core.supabase_auth import supabase_client_id
from app.db import repo


@asynccontextmanager
async def operation(session, user_id: int, kind: str, *, credits: int = 1):
    try:
        reservation = await repo.reserve_user_quota(
            session, user_id, operation_key=f"{kind}:{uuid.uuid4().hex}",
            amount=credits, ttl_seconds=3600,
        )
    except repo.QuotaLimitExceeded as exc:
        raise HTTPException(status_code=429, detail="QUOTA_EXCEEDED") from exc
    # The reservation must be visible before any external expenditure.
    await session.commit()
    try:
        yield reservation
    except BaseException:
        await session.rollback()
        await repo.release_user_quota(session, user_id, reservation_key=reservation["reservation_key"])
        await session.commit()
        raise
    else:
        await repo.confirm_user_quota(session, user_id, reservation_key=reservation["reservation_key"])
        await session.commit()


def metered(kind: str):
    """Use only on routes that already require a verified identity and DB session."""
    def decorate(fn):
        signature = inspect.signature(fn, eval_str=True)
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            values = signature.bind(*args, **kwargs).arguments
            session = values.get("session") or values.get("db")
            auth = values.get("auth_user") or values.get("_auth_user")
            identity = values.get("client_id")
            if auth is not None:
                identity = supabase_client_id(auth)
            if identity is None:
                identity = await require_authenticated_client_id(values["request"])
            user = await repo.get_or_create_user(session, web_client_id=identity)
            user_id = user.id
            async with operation(session, user_id, kind):
                return await fn(*args, **kwargs)
        wrapped.__signature__ = signature
        return wrapped
    return decorate

"""A web account must explicitly approve binding its Telegram identity."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from app.core.supabase_auth import require_supabase_user, supabase_client_id
from app.db import get_db, repo
from app.db.models import TelegramLinkToken, User

router = APIRouter(prefix="/account/telegram", tags=["account"])

@router.post("/link-token")
async def create_link(request: Request, auth_user=Depends(require_supabase_user), session=Depends(get_db)):
    if getattr(request.state, "telegram_id", None) is not None or auth_user.telegram_id is not None: raise HTTPException(403, "WEB_LOGIN_REQUIRED")
    user = await repo.get_or_create_user(session, web_client_id=supabase_client_id(auth_user))
    code = secrets.token_urlsafe(24)
    session.add(TelegramLinkToken(code_hash=hashlib.sha256(code.encode()).hexdigest(), user_id=user.id,
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)))
    await session.commit()
    return {"command": f"/link {code}", "expires_in_seconds": 600}

class LinkRequest(BaseModel):
    code: str = Field(min_length=16, max_length=128)

@router.post("/link")
async def consume_link(payload: LinkRequest, request: Request, session=Depends(get_db)):
    telegram_id = getattr(request.state, "telegram_id", None)
    if telegram_id is None: raise HTTPException(401, "BOT_SIGNATURE_REQUIRED")
    now = datetime.now(UTC).replace(tzinfo=None)
    digest = hashlib.sha256(payload.code.encode()).hexdigest()
    token = await session.scalar(select(TelegramLinkToken).where(TelegramLinkToken.code_hash == digest).with_for_update())
    if token is None or token.consumed_at is not None or token.expires_at <= now:
        raise HTTPException(400, "LINK_EXPIRED_OR_USED")
    user = await session.get(User, token.user_id)
    existing = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if existing and existing.id != user.id: raise HTTPException(409, "TELEGRAM_ALREADY_LINKED")
    claimed = await session.execute(update(TelegramLinkToken).where(
        TelegramLinkToken.code_hash == digest, TelegramLinkToken.consumed_at.is_(None),
        TelegramLinkToken.expires_at > now,
    ).values(consumed_at=now))
    if not claimed.rowcount: raise HTTPException(400, "LINK_EXPIRED_OR_USED")
    user.telegram_id = telegram_id
    await session.commit()
    return {"ok": True}

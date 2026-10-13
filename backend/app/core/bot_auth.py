"""Trusted bot requests bind identity, method, target, body and a one-time nonce."""
import hashlib
import hmac
import time
import re
from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core.config import get_settings

_nonces: dict[str, float] = {}

async def verify(request):
    settings = get_settings()
    if len(settings.bot_api_secret) < 32:
        raise HTTPException(503, "BOT_AUTH_NOT_CONFIGURED")
    try:
        telegram_id = int(request.headers["X-Telegram-Id"])
        timestamp = int(request.headers["X-Bot-Timestamp"])
        nonce = request.headers["X-Bot-Nonce"]
        if not 0 < telegram_id < 10**16 or abs(time.time() - timestamp) > 60 or not re.fullmatch(r"[a-f0-9]{32}", nonce):
            raise ValueError()
        body = await request.body()
        target = request.scope.get("raw_path", request.url.path.encode()).decode("ascii")
        if request.scope.get("query_string"):
            target += "?" + request.scope["query_string"].decode("ascii")
        canonical = f"{request.method}\n{target}\n{timestamp}\n{nonce}\n{telegram_id}\n{hashlib.sha256(body).hexdigest()}"
        expected = hmac.new(settings.bot_api_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers["X-Bot-Signature"]): raise ValueError()
    except (KeyError, ValueError, UnicodeError):
        raise HTTPException(401, "INVALID_BOT_SIGNATURE")
    if settings.app_env == "prod":
        from redis.asyncio import Redis
        client = Redis.from_url(settings.redis_url)
        try:
            fresh = await client.set(f"tendr:bot:nonce:{nonce}", "1", nx=True, ex=120)
        except Exception:
            raise HTTPException(503, "BOT_AUTH_UNAVAILABLE")
        finally: await client.aclose()
    else:
        now = time.time()
        for key in list(_nonces):
            if _nonces[key] < now: _nonces.pop(key, None)
        fresh = nonce not in _nonces
        _nonces[nonce] = now + 120
    if not fresh: raise HTTPException(401, "BOT_REQUEST_REPLAYED")
    return telegram_id

class BotSignatureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("X-Bot-Signature"):
            try: request.state.telegram_id = await verify(request)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return await call_next(request)

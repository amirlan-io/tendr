"""Ограничение частоты запросов к дорогостоящим эндпоинтам.

Зачем
----
До пентеста 2026-10-03 глобального rate limit в приложении не было: единственное
ограничение жило внутри `/api/browser/*` и ключом служил подделываемый
`client_id`. Это позволяло анонимно вызывать LLM/Tavily/Browser Use и
автоматически заводить бесконечное число гостевых аккаунтов с бесплатной
квотой (аудит 2026-10-03, P0 #2).

Как устроено
------------
- Ключ по IP: смена заголовка `X-Client-Id` лимит не обходит.
- Счётчики в памяти процесса. Этого достаточно для одного инстанса; при
  нескольких воркерах лимит умножается на их число — тогда нужен общий
  Redis-хранилище (в проекте REDIS_URL уже настроен).
- Окно скользящее, память периодически чистится, чтобы счётчики не росли
  бесконечно из-за неограниченного числа адресов.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

#: Префиксы эндпоинтов, которые тратят деньги (LLM, Tavily, Browser Use).
#: Лимит применяется только к ним: публичное чтение каталога лотов должно
#: остаться быстрым.
RATE_LIMITED_PREFIXES: tuple[str, ...] = (
    "/api/lots/search",
    "/api/lots/analyze",
    "/api/lots/analyze-upload",
    "/api/lots/analysis-jobs",
    "/api/lots/assistant/chat",
    "/api/products/search",
    "/api/products/deep-search",
    "/api/suppliers/search",
    "/api/suppliers/draft",
    "/api/sandbox/suppliers",
    "/api/b2g/workspaces",
    "/api/browser/run",
    "/api/browser/continue",
    "/api/applications",
)

#: Сколько запросов за окно допускается с одного адреса.
REQUESTS_PER_WINDOW = 30
WINDOW_SECONDS = 60

_HITS: dict[str, deque[float]] = defaultdict(deque)
_LAST_SWEEP = time.monotonic()


def _sweep(now: float) -> None:
    """Убрать окна, у которых истёк срок, и забыть пустые ключи."""
    cutoff = now - WINDOW_SECONDS
    stale = [key for key, hits in _HITS.items() if not hits or hits[-1] <= cutoff]
    for key in stale:
        _HITS.pop(key, None)


def _client_key(request: Request) -> str:
    """Prefer a hashed bearer identity, otherwise use the source address."""
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        digest = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:32]
        return f"account:{digest}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


async def _redis_count(key: str, now: float) -> tuple[int, int]:
    """Increment a shared fixed-window counter and return count/retry seconds."""
    from redis.asyncio import Redis

    settings = get_settings()
    bucket = int(now // WINDOW_SECONDS)
    redis_key = f"tendr:rate:{bucket}:{key}"
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        count = int(await client.incr(redis_key))
        if count == 1:
            await client.expire(redis_key, WINDOW_SECONDS + 2)
    finally:
        await client.aclose()
    retry_after = max(1, WINDOW_SECONDS - int(now % WINDOW_SECONDS))
    return count, retry_after


def reset_rate_limits() -> None:
    """Сбросить счётчики. Используется в тестах."""
    _HITS.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Ограничивает частоту дорогостоящих вызовов по IP."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not any(path.startswith(prefix) for prefix in RATE_LIMITED_PREFIXES):
            return await call_next(request)

        now = time.time()
        key = _client_key(request)
        settings = get_settings()

        if settings.app_env == "prod":
            try:
                count, retry_after = await _redis_count(key, now)
            except Exception:
                # Fail closed: an unavailable limiter must not turn paid APIs
                # into unlimited public endpoints.
                return JSONResponse(
                    status_code=503,
                    content={"detail": "RATE_LIMIT_UNAVAILABLE"},
                    headers={"Retry-After": "5"},
                )
            if count > REQUESTS_PER_WINDOW:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "RATE_LIMITED"},
                    headers={"Retry-After": str(retry_after)},
                )
            return await call_next(request)

        # Development/test fallback: one-process sliding window.
        now = time.monotonic()
        global _LAST_SWEEP
        if now - _LAST_SWEEP > WINDOW_SECONDS:
            _LAST_SWEEP = now
            _sweep(now)

        hits = _HITS[key]
        cutoff = now - WINDOW_SECONDS
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= REQUESTS_PER_WINDOW:
            retry_after = max(1, int(WINDOW_SECONDS - (now - hits[0])))
            return JSONResponse(
                status_code=429,
                content={"detail": "RATE_LIMITED"},
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        return await call_next(request)

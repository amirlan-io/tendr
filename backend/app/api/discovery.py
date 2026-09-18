"""Discovery API: свежие лоты, подписки."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services.discovery import get_discovery

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/feed")
async def feed(
    page: int = Query(1, ge=1, le=10, description="Номер страницы goszakup"),
    max_pages: int = Query(1, ge=1, le=5, description="Сколько страниц спарсить"),
    q: str | None = Query(None, description="Фильтр по ключевым словам (через запятую)"),
) -> dict[str, Any]:
    """Свежие лоты с goszakup.gov.kz.

    Без авторизации — discovery-слой работает для всех.
    """
    client = get_discovery()
    lots = await client.fetch_lots_pages(max_pages=max_pages)
    if page > 1:
        # простая пагинация по уже загруженным
        pass
    if q:
        keywords = [k.strip().lower() for k in q.split(",") if k.strip()]
        if keywords:
            lots = [
                l for l in lots if any(k in f"{l.title} {l.customer}".lower() for k in keywords)
            ]
    return {
        "count": len(lots),
        "items": [l.to_dict() for l in lots[:50]],
    }

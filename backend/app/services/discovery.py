"""Discovery-парсер: тянет свежие лоты с goszakup.gov.kz и матчит с подписками.

Использует HTML-список /ru/search/lots (Angular SSR отдаёт с данными).
Когда появится API-токен — заменим на /v3/lots?status=published.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.db.models import DiscoverySubscription


@dataclass
class DiscoveredLot:
    """Минимальная карточка лота из списка discovery."""

    lot_id: str
    title: str
    customer: str
    url: str
    discovered_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "lot_id": self.lot_id,
            "title": self.title,
            "customer": self.customer,
            "url": self.url,
            "discovered_at": self.discovered_at.isoformat(),
        }


# Паттерн блока лота в HTML-списке goszakup
_LOT_PATTERN = re.compile(
    r'href="/ru/announce/index/(\d+)"[^>]*>\s*<strong>([^<]+)</strong>.*?'
    r"<b>Заказчик:</b>\s*([^<]+?)<br>",
    re.DOTALL,
)

_BASE_URL = "https://goszakup.gov.kz"


class DiscoveryClient:
    """Клиент для парсинга списка лотов goszakup."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": "TendrBot/0.1 (+https://tendr.kz)"},
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_lots(self, page: int = 1) -> list[DiscoveredLot]:
        """Получить список свежих лотов с одной страницы."""
        url = f"{_BASE_URL}/ru/search/lots?page={page}"
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as e:
            logger.warning("Discovery fetch failed: {}", e)
            return []

        if resp.status_code != 200 or len(resp.text) < 1000:
            logger.warning("Discovery HTTP {}: {}", resp.status_code, url)
            return []

        return self._parse_page(resp.text)

    def _parse_page(self, html: str) -> list[DiscoveredLot]:
        """Распарсить HTML-страницу списка в карточки лотов."""
        now = datetime.utcnow()
        seen: set[str] = set()
        result: list[DiscoveredLot] = []

        for match in _LOT_PATTERN.finditer(html):
            lot_id, title, customer = match.groups()
            if lot_id in seen:
                continue  # на странице бывают дубли
            seen.add(lot_id)
            result.append(
                DiscoveredLot(
                    lot_id=lot_id.strip(),
                    title=title.strip(),
                    customer=customer.strip(),
                    url=f"{_BASE_URL}/ru/announce/index/{lot_id}",
                    discovered_at=now,
                )
            )
        return result

    async def fetch_lots_pages(self, max_pages: int = 3) -> list[DiscoveredLot]:
        """Несколько страниц = больше лотов. Возвращает уникальные."""
        tasks = [self.fetch_lots(p) for p in range(1, max_pages + 1)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_lots: dict[str, DiscoveredLot] = {}
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Discovery page failed: {}", r)
                continue
            for lot in r:
                all_lots[lot.lot_id] = lot
        return list(all_lots.values())


def _keywords_match(keywords: str, lot: DiscoveredLot) -> bool:
    """Проверить, матчит ли лот хотя бы одно ключевое слово."""
    if not keywords or not keywords.strip():
        return True
    kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    if not kws:
        return True
    text = f"{lot.title} {lot.customer}".lower()
    return any(kw in text for kw in kws)


async def find_matching_subscribers(
    session: AsyncSession, lot: DiscoveredLot
) -> list[DiscoverySubscription]:
    """Найти активные подписки, которым подходит этот лот."""
    stmt = select(DiscoverySubscription).where(
        DiscoverySubscription.is_active == True  # noqa: E712
    )
    result = await session.execute(stmt)
    all_subs = result.scalars().all()
    return [s for s in all_subs if _keywords_match(s.keywords, lot)]


async def notify_subscribers_for_lot(session: AsyncSession, lot: DiscoveredLot) -> list[int]:
    """Найти подписчиков и пометить, что им отправлено. Возвращает user_id.

    Реальная отправка в Telegram делается в bot/tasks.py (задача для следующей итерации).
    Здесь только резолвим подписчиков.
    """
    subs = await find_matching_subscribers(session, lot)
    user_ids = list({s.user_id for s in subs})
    if not user_ids:
        return []
    # Обновим last_notified_at
    await session.execute(
        update(DiscoverySubscription)
        .where(DiscoverySubscription.id.in_([s.id for s in subs]))
        .values(last_notified_at=datetime.utcnow())
    )
    return user_ids


# Singleton
_client: DiscoveryClient | None = None


def get_discovery() -> DiscoveryClient:
    global _client
    if _client is None:
        _client = DiscoveryClient()
    return _client


async def close_discovery() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None

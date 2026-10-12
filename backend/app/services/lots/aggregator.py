"""Агрегатор лотов с разных площадок (P0).

Подключаем все источники:
- zakup.gov.kz (основной, через GraphQL или REST v2)
- ets-tender.kz (коммерческие торги)
- Samruk-Казына
- Tizilim
- ERG

Возвращает объединённый список, дедуплицированный по (source, source_id).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from .graphql_client import GraphQLClient, SearchPageInfo
from .parser import LotParser, ParsedLot

logger = logging.getLogger(__name__)


class LotAggregator:
    """Собирает лоты со всех доступных площадок РК.

    По умолчанию использует GraphQL (быстрее, гибче).
    Можно переключиться на REST через use_graphql=False.
    """

    def __init__(self, api_token: str = "", api_url: str = ""):
        self.api_token = api_token
        self.parser = LotParser(api_token=api_token, api_url=api_url)
        self.graphql = GraphQLClient(api_token=api_token, api_url=api_url) if api_token else None
        self.page_info = SearchPageInfo()

    async def get_lots(
        self,
        query: str = "",
        region: str = "",
        platform: str = "",
        min_amount: float = 0,
        max_amount: float = 0,
        category: str = "",
        customer_bin: str = "",
        customer_bin_like: str = "",
        status: str = "active",
        procurement_method_ids: list[int] | None = None,
        published_from: str = "",
        published_to: str = "",
        cursor: int | None = None,
        only_with_amount: bool = False,
        use_graphql: bool = True,
        limit: int = 50,
    ) -> list[ParsedLot]:
        """Получить лоты со всех источников.

        По умолчанию GraphQL. Если упадёт — fallback на REST.
        """
        results: list[ParsedLot] = []

        # GraphQL путь (быстрый и гибкий)
        if use_graphql and self.graphql:
            try:
                lots = await self.graphql.search_lots(
                    query=query,
                    region=region,
                    category=category,
                    customer_bin=customer_bin,
                    customer_bin_like=customer_bin_like,
                    status=status,
                    procurement_method_ids=procurement_method_ids,
                    published_from=published_from,
                    published_to=published_to,
                    cursor=cursor,
                    min_amount=min_amount,
                    max_amount=max_amount,
                    only_with_amount=only_with_amount,
                    limit=limit,
                )
                results.extend(lots)
                self.page_info = self.graphql.page_info
                logger.info(f"[Aggregator] GraphQL returned {len(results)} lots")
                # Пустой ответ — корректный результат, его нельзя подменять
                # fallback/demo-записями другого запроса.
                return self._dedupe(results)[:limit]
            except Exception as e:
                # REST /trd-buy возвращает объявления, а не отдельные лоты.
                # Подмена после timeout делает выдачу фактически неверной.
                logger.exception("[Aggregator] official lots GraphQL failed")
                raise RuntimeError("Official Goszakup lots registry is unavailable") from e

        # REST fallback
        try:
            lots = await self.parser.search_lots(
                query=query,
                region=region,
                platform=platform,
                min_amount=min_amount,
                max_amount=max_amount,
                category=category,
                limit=limit,
            )
            results.extend(lots)
        except Exception as e:
            logger.exception(f"[Aggregator] REST failed: {e}")

        unique = self._dedupe(results)[:limit]
        self.page_info = SearchPageInfo(
            total_count=len(unique),
            has_next_page=False,
            fetched_at=datetime.now(UTC),
            total_is_exact=True,
        )
        return unique

    @staticmethod
    def _dedupe(lots: list[ParsedLot]) -> list[ParsedLot]:
        """Дедупликация по (source, source_id)."""
        seen = set()
        unique = []
        for lot in lots:
            key = (lot.source, lot.source_id)
            if key not in seen:
                seen.add(key)
                unique.append(lot)
        return unique

    async def get_lot_by_id(self, source: str, source_id: str) -> ParsedLot | None:
        """Получить один лот по source + source_id."""
        if source == "zakup_gov" and self.graphql:
            try:
                lots = await self.graphql.search_lots(limit=200)
                for lot in lots:
                    if lot.source == source and lot.source_id == source_id:
                        return lot
            except Exception as e:
                logger.warning(f"[Aggregator] GraphQL get_lot_by_id failed: {e}")
        # REST fallback
        try:
            lots = await self.parser.search_lots(limit=200)
            for lot in lots:
                if lot.source == source and lot.source_id == source_id:
                    return lot
        except Exception as e:
            logger.warning(f"[Aggregator] REST get_lot_by_id failed: {e}")
        return None

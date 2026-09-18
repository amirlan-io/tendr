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
from typing import Any

from .graphql_client import GraphQLClient
from .parser import LotParser, ParsedLot

logger = logging.getLogger(__name__)


class LotAggregator:
    """Собирает лоты со всех доступных площадок РК.

    По умолчанию использует GraphQL (быстрее, гибче).
    Можно переключиться на REST через use_graphql=False.
    """

    def __init__(self, api_token: str = ""):
        self.api_token = api_token
        self.parser = LotParser(api_token=api_token)
        self.graphql = GraphQLClient(api_token=api_token) if api_token else None

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
                    customer_bin=customer_bin,
                    customer_bin_like=customer_bin_like,
                    min_amount=min_amount,
                    max_amount=max_amount,
                    only_with_amount=only_with_amount,
                    limit=limit,
                )
                results.extend(lots)
                if results:
                    logger.info(
                        f"[Aggregator] GraphQL returned {len(results)} lots"
                    )
                    return self._dedupe(results)[:limit]
            except Exception as e:
                logger.warning(
                    f"[Aggregator] GraphQL failed: {e}, fallback to REST"
                )

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

        return self._dedupe(results)[:limit]

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

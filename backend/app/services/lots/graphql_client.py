"""GraphQL клиент для zakup.gov.kz v2.

GraphQL endpoint: https://ows.goszakup.gov.kz/v2/graphql
Схема: https://ows.goszakup.gov.kz/help/v3/schema/

Преимущества GraphQL над REST:
- Один запрос вместо нескольких (trd_buy + lots + subject)
- Выбираем только нужные поля
- Поддержка пагинации через cursor (search_after)
- Встроенная фильтрация

Пример:
    query {
        trd_buy(
            limit: 50,
            filters: {
                ref_buy_status_id: [210, 220, 230],
                name_ru: { LIKE: "%ноутбук%" }
            }
        ) {
            id
            name_ru
            name_kz
            number_anno
            org_bin
            total_sum
            publish_date
            end_date
            ref_buy_status_id
        }
    }
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .parser import LotParser, ParsedLot

logger = logging.getLogger(__name__)


# GraphQL запрос — возвращает все нужные поля
# Можно выбирать какие поля нужны
TRD_BUY_QUERY = """
query SearchLots(
    $limit: Int!
    $after: Int
    $filter: TrdBuyFiltersInput
) {
    trd_buy(limit: $limit, after: $after, filters: $filter) {
        id
        number_anno
        name_ru
        name_kz
        org_bin
        ref_buy_status_id
        ref_trade_methods_id
        publish_date
        start_date
        end_date
        total_sum
        count_lots
        system_id
    }
}
"""


class GraphQLClient:
    """Клиент для GraphQL endpoint zakup.gov.kz v2.

    Пример:
        client = GraphQLClient(api_token="...")
        items = await client.search_lots(query="ноутбук", limit=10)
    """

    ENDPOINT = "https://ows.goszakup.gov.kz/v2/graphql"
    TIMEOUT = 30.0

    def __init__(self, api_token: str):
        self.api_token = api_token
        self.parser = LotParser()

    async def search_lots(
        self,
        query: str = "",
        region: str = "",
        customer_bin: str = "",
        customer_bin_like: str = "",
        min_amount: float = 0,
        max_amount: float = 0,
        only_with_amount: bool = False,
        limit: int = 50,
    ) -> list[ParsedLot]:
        """Поиск лотов через GraphQL.

        Args:
            query: ключевые слова для поиска по nameRu
            region: регион (пока не поддерживается в GraphQL trd_buy)
            customer_bin: точный БИН заказчика
            customer_bin_like: подстрока БИН
            min_amount, max_amount: фильтр по total_sum
            only_with_amount: только лоты с указанной суммой
            limit: сколько вернуть (макс 50 в одном запросе)
        """
        # Строим filter для GraphQL
        # Поля фильтра согласно схеме zakup.gov.kz
        filter_dict: dict[str, Any] = {}

        # text search (nameRu) — GraphQL не поддерживает LIKE в trd_buy,
        # поэтому запоминаем для пост-фильтрации на стороне Python
        text_query = query.strip() if query else ""

        if customer_bin:
            # GraphQL ожидает String для org_bin (не объект {LIKE})
            filter_dict["org_bin"] = customer_bin
        # customer_bin_like: GraphQL не поддерживает LIKE для org_bin,
        # используем пост-фильтрацию в Python ниже

        if min_amount:
            filter_dict["total_sum"] = {"GTE": min_amount}
        if max_amount:
            if "total_sum" in filter_dict:
                # AND-композиция (упрощенно)
                filter_dict["total_sum"] = {
                    "GTE": min_amount,
                    "LTE": max_amount,
                }
            else:
                filter_dict["total_sum"] = {"LTE": max_amount}

        if only_with_amount:
            filter_dict["total_sum"] = filter_dict.get("total_sum", {"GTE": 0.01})

        # region пока не поддерживается в trd_buy GraphQL

        variables = {
            "limit": min(limit, 50),
            "filter": filter_dict if filter_dict else None,
        }

        payload = {
            "query": TRD_BUY_QUERY,
            "variables": variables,
        }

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(self.ENDPOINT, json=payload, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(
                f"GraphQL returned {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()

        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")

        # Извлекаем items
        items = data.get("data", {}).get("trd_buy", [])
        total = (
            data.get("extensions", {})
            .get("pageInfo", {})
            .get("totalCount", len(items))
        )

        logger.info(
            f"[GraphQL] got {len(items)} items (total in DB: {total}) "
            f"with filter={filter_dict}"
        )

        # Парсим через общий parser
        parsed = [self._graphql_to_parsed(item) for item in items]

        # Пост-фильтрация по тексту (GraphQL не поддерживает LIKE в trd_buy)
        if text_query:
            text_lower = text_query.lower()
            parsed = [
                lot for lot in parsed
                if text_lower in (lot.title or "").lower()
                or text_lower in (lot.description or "").lower()
            ]
            logger.info(f"[GraphQL] text filter '{text_query}': {len(parsed)} lots")

        # Пост-фильтрация по подстроке в org_bin (customerBinLike)
        if customer_bin_like:
            like_lower = customer_bin_like.lower()
            parsed = [
                lot for lot in parsed
                if like_lower in (lot.organizer_bin or "").lower()
            ]
            logger.info(
                f"[GraphQL] org_bin like '{customer_bin_like}': {len(parsed)} lots"
            )

        return parsed[:limit]

    def _graphql_to_parsed(self, item: dict) -> ParsedLot:
        """Конвертирует ответ GraphQL в ParsedLot."""
        # zakup.gov.kz — это SPA с роутами /ru/announce/{id}
        # Используем несколько форматов (id, number_anno)
        lot_id_val = item.get("id", "")
        lot_num = item.get("number_anno", "")
        if lot_num:
            source_url = f"https://v3bl.goszakup.gov.kz/ru/announce/index/{lot_num}"
        elif lot_id_val:
            source_url = f"https://v3bl.goszakup.gov.kz/ru/announce/index/{lot_id_val}"
        else:
            source_url = "https://v3bl.goszakup.gov.kz/ru/announce"

        return ParsedLot(
            source="zakup_gov",
            source_id=str(lot_id_val),
            title=item.get("name_ru") or item.get("name_kz") or "",
            description=item.get("name_kz"),  # казахский как описание
            category=None,  # не возвращается в trd_buy
            procurement_method=self._map_method(item.get("ref_trade_methods_id")),
            platform="zakup.gov.kz",
            amount_kzt=self._safe_float(item.get("total_sum")),
            price_per_unit=None,
            region=None,  # не в trd_buy, нужно из subject
            delivery_address=None,
            publish_date=self._parse_dt(item.get("publish_date")),
            deadline_date=self._parse_dt(item.get("end_date")),
            organizer=item.get("customer_name_ru"),  # может отсутствовать
            organizer_bin=item.get("org_bin"),
            status=self._map_status(item.get("ref_buy_status_id")),
            source_url=source_url,
            raw_data=item,
        )

    @staticmethod
    def _map_method(ref_id: Optional[int]) -> Optional[str]:
        """Маппинг ref_trade_methods_id → название (основные)."""
        if ref_id is None:
            return None
        mapping = {
            1: "электронный аукцион",
            2: "конкурс",
            3: "запрос ценовых предложений",
            7: "аукцион",
            23: "из одного источника",
            118: "через товарные биржи",
        }
        return mapping.get(ref_id, f"способ #{ref_id}")

    @staticmethod
    def _map_status(ref_id: Optional[int]) -> str:
        """Маппинг ref_buy_status_id → читаемый статус."""
        if ref_id is None:
            return "Опубликован"
        mapping = {
            210: "Опубликован (приём заявок)",
            220: "Опубликован (обсуждение)",
            230: "Опубликован",
            240: "Опубликован (приём ценовых)",
            310: "Приём заявок",
            360: "Итоги (победитель)",
            370: "Итоги",
            390: "Завершён",
            410: "Отменён",
        }
        return mapping.get(ref_id, f"статус #{ref_id}")

    @staticmethod
    def _safe_float(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_dt(s: Any) -> Optional["datetime"]:  # type: ignore
        """Парсит дату из разных форматов GraphQL."""
        if not s:
            return None
        from datetime import datetime
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(str(s), fmt)
            except ValueError:
                continue
        return None

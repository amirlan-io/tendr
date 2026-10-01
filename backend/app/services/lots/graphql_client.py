"""Клиент официального GraphQL API государственных закупок РК.

``trd_buy`` — реестр объявлений, а ``lots`` — отдельные лоты внутри них.
Каталог Tendr показывает именно ``lots``.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from .parser import LotParser, ParsedLot

logger = logging.getLogger(__name__)

LOTS_QUERY = """
query SearchLots($limit: Int!, $after: Int, $filter: LotsFiltersInput) {
  lots(limit: $limit, after: $after, filters: $filter) {
    id lot_number ref_lot_status_id last_update_date count amount
    name_ru name_kz description_ru description_kz
    customer_id customer_bin trd_buy_number_anno trd_buy_id
    point_list index_date
  }
}
"""

ANNOUNCEMENTS_QUERY = """
query Announcements($limit: Int!, $filter: TrdBuyFiltersInput) {
  trd_buy(limit: $limit, filters: $filter) {
    id number_anno name_ru customer_bin org_bin
    publish_date start_date end_date ref_buy_status_id
    ref_trade_methods_id ref_subject_type_id
  }
}
"""


class GraphQLClient:
    """Клиент реестра реальных лотов zakup.gov.kz v2."""

    ENDPOINT = "https://ows.goszakup.gov.kz/v2/graphql"
    TIMEOUT = 30.0
    PAGE_SIZE = 200
    MAX_SCAN_PAGES = 5

    def __init__(self, api_token: str, api_url: str = ""):
        self.api_token = api_token
        base_url = (api_url or "https://ows.goszakup.gov.kz/v2").rstrip("/")
        self.endpoint = base_url if base_url.endswith("/graphql") else f"{base_url}/graphql"
        self.parser = LotParser()

    async def search_lots(
        self,
        query: str = "",
        region: str = "",
        category: str = "",
        customer_bin: str = "",
        customer_bin_like: str = "",
        min_amount: float = 0,
        max_amount: float = 0,
        only_with_amount: bool = False,
        limit: int = 50,
    ) -> list[ParsedLot]:
        """Ищет отдельные лоты и обогащает их данными объявления/заказчика."""
        # В реестре lots нет готового названия региона. Пока не подключён KATO,
        # лучше честно вернуть пустой ответ, чем показать лоты другого региона.
        if region:
            logger.warning("[GraphQL] region filter needs KATO mapping; returning no results")
            return []

        text_query = (query or "").strip().lower()
        normalized_category = (category or "").strip().lower()
        bin_like = (customer_bin_like or "").strip().lower()
        wanted = max(1, min(int(limit), self.PAGE_SIZE))
        filters: dict[str, Any] = {}
        if customer_bin:
            filters["customer_bin"] = customer_bin.strip()
        # Официальный API умеет искать точный номер по всему реестру. Для
        # обычных слов полнотекстового фильтра нет — ниже просматриваем свежие
        # страницы и фильтруем их локально.
        if re.fullmatch(r"\d{6,}(?:-[^\s]+)?", (query or "").strip()):
            filters["lot_number"] = (query or "").strip()

        needs_scan = bool(
            text_query or normalized_category or bin_like or min_amount
            or max_amount or only_with_amount
        )
        page_size = self.PAGE_SIZE if needs_scan else wanted
        page_count = self.MAX_SCAN_PAGES if needs_scan else 1
        matches: list[ParsedLot] = []
        after: int | None = None
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            for _ in range(page_count):
                data = await self._request(
                    client,
                    LOTS_QUERY,
                    {"limit": page_size, "after": after, "filter": filters or None},
                    headers,
                )
                items = data.get("data", {}).get("lots", []) or []
                if not items:
                    break

                # Сначала дешёвая фильтрация по полям самого лота. Иначе один
                # текстовый поиск заставляет обогащать до 1000 чужих записей и
                # официальный API успевает отдать timeout.
                candidates = [
                    item for item in items
                    if self._raw_matches(
                        item,
                        text_query=text_query,
                        customer_bin_like=bin_like,
                        min_amount=min_amount,
                        max_amount=max_amount,
                        only_with_amount=only_with_amount,
                    )
                ]
                announcement_map = await self._load_announcements(client, candidates, headers)

                # Категория хранится у объявления. Отсекаем её до запроса
                # названий заказчиков, чтобы не перегружать subjects.
                if normalized_category:
                    category_ids = {"товар": 1, "работа": 2, "услуга": 3}
                    expected_id = category_ids.get(normalized_category)
                    candidates = [
                        item for item in candidates
                        if self._safe_int(
                            (announcement_map.get(self._safe_int(item.get("trd_buy_id"))) or {})
                            .get("ref_subject_type_id")
                        ) == expected_id
                    ]

                subject_map = await self._load_subjects(client, candidates, headers)
                for item in candidates:
                    announcement = announcement_map.get(self._safe_int(item.get("trd_buy_id")))
                    customer_name = subject_map.get(str(item.get("customer_bin") or ""))
                    lot = self._graphql_to_parsed(item, announcement, customer_name)
                    if not self._matches(
                        lot,
                        text_query=text_query,
                        category=normalized_category,
                        customer_bin_like=bin_like,
                        min_amount=min_amount,
                        max_amount=max_amount,
                        only_with_amount=only_with_amount,
                    ):
                        continue
                    matches.append(lot)
                    if len(matches) >= wanted:
                        return matches[:wanted]

                page_info = data.get("extensions", {}).get("pageInfo", {}) or {}
                next_after = self._safe_int(page_info.get("lastId"))
                if next_after is None:
                    next_after = self._safe_int(items[-1].get("id"))
                if next_after is None or next_after == after or len(items) < page_size:
                    break
                after = next_after

        logger.info("[GraphQL] actual lots matched=%s query=%r", len(matches), text_query)
        return matches[:wanted]

    @classmethod
    def _raw_matches(
        cls,
        item: dict[str, Any],
        *,
        text_query: str,
        customer_bin_like: str,
        min_amount: float,
        max_amount: float,
        only_with_amount: bool,
    ) -> bool:
        if text_query:
            haystack = " ".join(str(item.get(key) or "") for key in (
                "lot_number", "name_ru", "name_kz", "description_ru",
                "description_kz", "customer_bin",
            )).lower()
            if text_query not in haystack:
                return False
        customer_bin = str(item.get("customer_bin") or "").lower()
        if customer_bin_like and customer_bin_like not in customer_bin:
            return False
        amount = cls._safe_float(item.get("amount"))
        if only_with_amount and (amount is None or amount <= 0):
            return False
        if min_amount and (amount is None or amount < min_amount):
            return False
        return not (max_amount and (amount is None or amount > max_amount))

    async def _request(
        self,
        client: httpx.AsyncClient,
        query: str,
        variables: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        response = await client.post(
            self.endpoint,
            json={"query": query, "variables": variables},
            headers=headers,
        )
        if response.status_code != 200:
            raise RuntimeError(f"GraphQL returned {response.status_code}: {response.text[:200]}")
        data = response.json()
        if data.get("errors"):
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data

    async def _load_announcements(
        self,
        client: httpx.AsyncClient,
        lots: list[dict[str, Any]],
        headers: dict[str, str],
    ) -> dict[int, dict[str, Any]]:
        ids = sorted({
            value for item in lots
            if (value := self._safe_int(item.get("trd_buy_id"))) is not None
        })
        if not ids:
            return {}
        data = await self._request(
            client,
            ANNOUNCEMENTS_QUERY,
            {"limit": min(len(ids), self.PAGE_SIZE), "filter": {"id": ids}},
            headers,
        )
        result: dict[int, dict[str, Any]] = {}
        for item in data.get("data", {}).get("trd_buy", []) or []:
            item_id = self._safe_int(item.get("id"))
            if item_id is not None:
                result[item_id] = item
        return result

    async def _load_subjects(
        self,
        client: httpx.AsyncClient,
        lots: list[dict[str, Any]],
        headers: dict[str, str],
    ) -> dict[str, str]:
        bins = sorted({str(item.get("customer_bin") or "").strip() for item in lots})
        bins = [value for value in bins if value]
        result: dict[str, str] = {}
        for offset in range(0, len(bins), 50):
            chunk = bins[offset : offset + 50]
            declarations = ", ".join(f"$bin{i}: String" for i in range(len(chunk)))
            selections = "\n".join(
                f's{i}: subjects(filters: {{bin: $bin{i}}}, limit: 1) '
                "{ bin name_ru full_name_ru }"
                for i in range(len(chunk))
            )
            gql = f"query SubjectBatch({declarations}) {{\n{selections}\n}}"
            variables = {f"bin{i}": value for i, value in enumerate(chunk)}
            data = await self._request(client, gql, variables, headers)
            payload = data.get("data", {}) or {}
            for i, requested_bin in enumerate(chunk):
                subjects = payload.get(f"s{i}", []) or []
                if subjects:
                    subject = subjects[0]
                    result[requested_bin] = (
                        subject.get("full_name_ru") or subject.get("name_ru") or requested_bin
                    )
        return result

    def _graphql_to_parsed(
        self,
        item: dict[str, Any],
        announcement: dict[str, Any] | None,
        customer_name: str | None,
    ) -> ParsedLot:
        announcement = announcement or {}
        lot_number = str(item.get("lot_number") or item.get("id") or "")
        announcement_number = str(
            item.get("trd_buy_number_anno") or announcement.get("number_anno")
            or item.get("trd_buy_id") or ""
        )
        source_url = (
            f"https://v3bl.goszakup.gov.kz/ru/announce/index/{announcement_number}"
            if announcement_number else "https://v3bl.goszakup.gov.kz/ru/announce"
        )
        category_map = {1: "товар", 2: "работа", 3: "услуга"}
        subject_type = self._safe_int(announcement.get("ref_subject_type_id"))
        raw_data = dict(item)
        raw_data["announcement"] = announcement
        return ParsedLot(
            source="zakup_gov",
            source_id=lot_number,
            title=item.get("name_ru") or item.get("name_kz") or "Без названия",
            description=item.get("description_ru") or item.get("description_kz"),
            category=category_map.get(subject_type),
            procurement_method=self._map_method(
                self._safe_int(announcement.get("ref_trade_methods_id"))
            ),
            platform="zakup.gov.kz",
            amount_kzt=self._safe_float(item.get("amount")),
            price_per_unit=None,
            region=None,
            delivery_address=None,
            publish_date=self._parse_dt(announcement.get("publish_date") or item.get("index_date")),
            deadline_date=self._parse_dt(announcement.get("end_date")),
            organizer=customer_name or str(item.get("customer_bin") or "") or None,
            organizer_bin=str(item.get("customer_bin") or "") or None,
            status=self._map_lot_status(
                self._safe_int(item.get("ref_lot_status_id")),
                self._safe_int(announcement.get("ref_buy_status_id")),
            ),
            source_url=source_url,
            raw_data=raw_data,
        )

    @staticmethod
    def _matches(
        lot: ParsedLot,
        *,
        text_query: str,
        category: str,
        customer_bin_like: str,
        min_amount: float,
        max_amount: float,
        only_with_amount: bool,
    ) -> bool:
        if text_query:
            haystack = " ".join(filter(None, [
                lot.source_id, lot.title, lot.description, lot.organizer, lot.organizer_bin,
            ])).lower()
            if text_query not in haystack:
                return False
        if category and (lot.category or "").lower() != category:
            return False
        if customer_bin_like and customer_bin_like not in (lot.organizer_bin or "").lower():
            return False
        if only_with_amount and (lot.amount_kzt is None or lot.amount_kzt <= 0):
            return False
        if min_amount and (lot.amount_kzt is None or lot.amount_kzt < min_amount):
            return False
        return not (
            max_amount and (lot.amount_kzt is None or lot.amount_kzt > max_amount)
        )

    @staticmethod
    def _map_method(ref_id: int | None) -> str | None:
        if ref_id is None:
            return None
        mapping = {
            1: "электронный аукцион", 2: "конкурс",
            3: "запрос ценовых предложений", 7: "аукцион",
            23: "из одного источника", 118: "через товарные биржи",
        }
        return mapping.get(ref_id, f"способ #{ref_id}")

    @staticmethod
    def _map_lot_status(
        lot_status_id: int | None, announcement_status_id: int | None
    ) -> str:
        lot_mapping = {
            110: "Опубликован", 120: "На рассмотрении", 220: "Приём заявок",
            240: "Приём ценовых предложений", 360: "Подведены итоги", 410: "Отменён",
        }
        if lot_status_id in lot_mapping:
            return lot_mapping[lot_status_id]
        announcement_mapping = {
            210: "Опубликован (приём заявок)", 220: "Опубликован (обсуждение)",
            230: "Опубликован", 240: "Опубликован (приём ценовых)",
            310: "Приём заявок", 360: "Итоги (победитель)", 370: "Итоги",
            390: "Завершён", 410: "Отменён",
        }
        if announcement_status_id in announcement_mapping:
            return announcement_mapping[announcement_status_id]
        return f"Статус лота #{lot_status_id}" if lot_status_id is not None else "Опубликован"

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if not value:
            return None
        normalized = str(value).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value), fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
        return None

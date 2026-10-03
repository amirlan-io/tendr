"""Клиент официального GraphQL API V3 государственных закупок РК.

V3 умеет искать по названию и описанию по всему реестру с учётом
морфологии. Это принципиально важнее локального перебора нескольких свежих
страниц: пользователь должен находить лот независимо от его позиции в ленте.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from .parser import LotParser, ParsedLot

logger = logging.getLogger(__name__)

LOTS_QUERY = """
query SearchLots($limit: Int, $after: Int, $filter: LotsFiltersInput) {
  lots: Lots(limit: $limit, after: $after, filter: $filter) {
    id
    lot_number: lotNumber
    ref_lot_status_id: refLotStatusId
    last_update_date: lastUpdateDate
    count amount
    name_ru: nameRu
    name_kz: nameKz
    description_ru: descriptionRu
    description_kz: descriptionKz
    customer_id: customerId
    customer_bin: customerBin
    customer_name_ru: customerNameRu
    customer_name_kz: customerNameKz
    trd_buy_number_anno: trdBuyNumberAnno
    trd_buy_id: trdBuyId
    ref_trade_methods_id: refTradeMethodsId
    ref_buy_trade_methods_id: refBuyTradeMethodsId
    point_list: pointList
    pln_point_kato_list: plnPointKatoList
    index_date: indexDate
    announcement: TrdBuy {
      id
      number_anno: numberAnno
      name_ru: nameRu
      customer_bin: customerBin
      org_bin: orgBin
      publish_date: publishDate
      start_date: startDate
      end_date: endDate
      ref_buy_status_id: refBuyStatusId
      ref_trade_methods_id: refTradeMethodsId
      ref_subject_type_id: refSubjectTypeId
    }
  }
}
"""


@dataclass
class SearchPageInfo:
    """Метаданные страницы, которые официальный V3 возвращает в extensions."""

    total_count: int = 0
    has_next_page: bool = False
    next_cursor: int | None = None
    fetched_at: datetime | None = None
    last_updated_at: datetime | None = None
    total_is_exact: bool = True


class GraphQLClient:
    """Клиент реестра реальных лотов zakup.gov.kz V3."""

    ENDPOINT = "https://ows.goszakup.gov.kz/v3/graphql"
    TIMEOUT = 30.0
    PAGE_SIZE = 200
    MAX_SCAN_PAGES = 5

    def __init__(self, api_token: str, api_url: str = ""):
        self.api_token = api_token
        base_url = (api_url or "https://ows.goszakup.gov.kz/v3").rstrip("/")
        # Старые .env проекта указывали V2. Для полнотекстового поиска нужен
        # V3; токен портала подходит для обоих API.
        base_url = re.sub(r"/v2(?=/|$)", "/v3", base_url)
        self.endpoint = base_url if base_url.endswith("/graphql") else f"{base_url}/graphql"
        self.parser = LotParser()
        self.page_info = SearchPageInfo()

    async def search_lots(
        self,
        query: str = "",
        region: str = "",
        category: str = "",
        customer_bin: str = "",
        customer_bin_like: str = "",
        status: str = "active",
        procurement_method_ids: list[int] | None = None,
        published_from: str = "",
        published_to: str = "",
        cursor: int | None = None,
        min_amount: float = 0,
        max_amount: float = 0,
        only_with_amount: bool = False,
        limit: int = 50,
    ) -> list[ParsedLot]:
        """Ищет отдельные лоты и обогащает их данными объявления/заказчика."""
        text_query = (query or "").strip().lower()
        normalized_category = (category or "").strip().lower()
        normalized_region = (region or "").strip()
        wanted = max(1, min(int(limit), self.PAGE_SIZE))
        filters: dict[str, Any] = {}
        if customer_bin:
            filters["customerBin"] = customer_bin.strip()

        raw_query = (query or "").strip()
        exact_lot_number = bool(re.fullmatch(r"\d{6,}(?:-[^\s]+)?", raw_query))
        if exact_lot_number:
            filters["lotNumber"] = raw_query
        elif text_query:
            # В V3 ведущая * включает морфологический поиск одновременно по
            # названию и описанию. Например, «сайт» найдёт «сайтов» и «сайта».
            filters["nameDescriptionRu"] = f"*{raw_query}"

        if customer_bin_like:
            normalized_customer = customer_bin_like.strip()
            if normalized_customer.isdigit():
                filters["customerBin"] = normalized_customer
            else:
                filters["customerNameRu"] = f"*{normalized_customer}"

        if min_amount or max_amount:
            amount_from = max(0.0, float(min_amount or 0))
            if max_amount:
                filters["amount"] = [amount_from, float(max_amount)]
            else:
                filters["amount"] = [amount_from]

        status_ids = {
            "active": [220, 240],
            "published": [220],
            "offers": [240],
            "archive": [360, 370, 410],
            "all": [],
        }.get((status or "active").strip().lower(), [220, 240])
        if status_ids:
            filters["refLotStatusId"] = status_ids

        normalized_methods = sorted(
            {int(method_id) for method_id in (procurement_method_ids or []) if int(method_id) > 0}
        )
        if normalized_methods:
            filters["refBuyTradeMethodsId"] = normalized_methods

        if published_from or published_to:
            date_range = [value for value in (published_from, published_to) if value]
            filters["indexDate"] = date_range

        # Для точного девятизначного КАТО фильтр полностью выполняет V3.
        # Двузначный код области поддерживаем как удобный префикс, но тогда
        # приходится просматривать несколько уже серверно отфильтрованных страниц.
        region_is_exact = bool(re.fullmatch(r"\d{9}", normalized_region))
        region_prefix = normalized_region if re.fullmatch(r"\d{2}", normalized_region) else ""
        if region_is_exact:
            filters["plnPointKatoList"] = normalized_region

        # Категория находится во вложенном объявлении и не входит в фильтр
        # LotsFiltersInput. Только для неё просматриваем несколько страниц уже
        # серверно отфильтрованной выдачи; текст и сумма фильтруются самим API.
        needs_scan = bool(normalized_category or region_prefix)
        page_size = self.PAGE_SIZE if needs_scan else wanted
        page_count = self.MAX_SCAN_PAGES if needs_scan else 1
        matches: list[ParsedLot] = []
        after: int | None = cursor
        official_total = 0
        has_next_page = False
        next_cursor: int | None = None
        latest_update: datetime | None = None
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
                page_info = data.get("extensions", {}).get("pageInfo", {}) or {}
                official_total = self._safe_int(page_info.get("totalCount")) or 0
                has_next_page = bool(page_info.get("hasNextPage"))
                if not items:
                    break

                # Текст и диапазон уже отфильтрованы сервером V3. Локально
                # оставляем только защитную проверку суммы и БИН.
                candidates = [
                    item for item in items
                    if self._raw_matches(
                        item,
                        text_query="",
                        customer_bin_like="",
                        min_amount=min_amount,
                        max_amount=max_amount,
                        only_with_amount=only_with_amount,
                    )
                ]
                announcement_map = {
                    trd_buy_id: announcement
                    for item in candidates
                    if isinstance((announcement := item.get("announcement")), dict)
                    and (trd_buy_id := self._safe_int(item.get("trd_buy_id"))) is not None
                }

                # Категория хранится у вложенного объявления.
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

                if region_prefix:
                    candidates = [
                        item for item in candidates
                        if any(
                            str(code or "").startswith(region_prefix)
                            for code in self._as_list(item.get("pln_point_kato_list"))
                        )
                    ]

                for candidate_index, item in enumerate(candidates):
                    announcement = announcement_map.get(self._safe_int(item.get("trd_buy_id")))
                    customer_name = (
                        item.get("customer_name_ru") or item.get("customer_name_kz")
                    )
                    lot = self._graphql_to_parsed(item, announcement, customer_name)
                    if not self._matches(
                        lot,
                        # Не повторяем substring-проверку после морфологического
                        # поиска API: «сайт» должен принимать также «сайтов».
                        text_query="",
                        category=normalized_category,
                        customer_bin_like="",
                        min_amount=min_amount,
                        max_amount=max_amount,
                        only_with_amount=only_with_amount,
                    ):
                        continue
                    matches.append(lot)
                    item_updated = self._parse_dt(
                        item.get("last_update_date") or item.get("index_date")
                    )
                    if item_updated and (latest_update is None or item_updated > latest_update):
                        latest_update = item_updated
                    if len(matches) >= wanted:
                        next_cursor = (
                            self._safe_int(item.get("id"))
                            if needs_scan
                            else self._safe_int(page_info.get("lastId"))
                        )
                        page_has_more = has_next_page or candidate_index < len(candidates) - 1
                        self.page_info = SearchPageInfo(
                            total_count=(len(matches) if needs_scan else official_total),
                            has_next_page=page_has_more,
                            next_cursor=next_cursor,
                            fetched_at=datetime.now(UTC),
                            last_updated_at=latest_update,
                            total_is_exact=not needs_scan,
                        )
                        return matches[:wanted]

                next_after = self._safe_int(page_info.get("lastId"))
                if next_after is None:
                    next_after = self._safe_int(items[-1].get("id"))
                if next_after is None or next_after == after or len(items) < page_size:
                    next_cursor = next_after
                    break
                after = next_after
                next_cursor = next_after

        logger.info("[GraphQL] actual lots matched=%s query=%r", len(matches), text_query)
        self.page_info = SearchPageInfo(
            total_count=(len(matches) if needs_scan else official_total),
            has_next_page=has_next_page,
            next_cursor=next_cursor,
            fetched_at=datetime.now(UTC),
            last_updated_at=latest_update,
            total_is_exact=not needs_scan,
        )
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
        kato_codes = [str(code) for code in self._as_list(item.get("pln_point_kato_list")) if code]
        kato_code = kato_codes[0] if kato_codes else None
        method_id = (
            self._safe_int(item.get("ref_buy_trade_methods_id"))
            or self._safe_int(item.get("ref_trade_methods_id"))
            or self._safe_int(announcement.get("ref_trade_methods_id"))
        )
        raw_data = dict(item)
        raw_data["announcement"] = announcement
        return ParsedLot(
            source="zakup_gov",
            source_id=lot_number,
            title=item.get("name_ru") or item.get("name_kz") or "Без названия",
            description=item.get("description_ru") or item.get("description_kz"),
            category=category_map.get(subject_type),
            procurement_method=self._map_method(method_id),
            platform="zakup.gov.kz",
            amount_kzt=self._safe_float(item.get("amount")),
            price_per_unit=None,
            region=self._region_from_kato(kato_code),
            delivery_address=(f"КАТО {kato_code}" if kato_code else None),
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
            6: "из одного источника по несостоявшимся закупкам",
            23: "из одного источника", 118: "через товарные биржи",
        }
        return mapping.get(ref_id, f"способ #{ref_id}")

    @staticmethod
    def _map_lot_status(
        lot_status_id: int | None, announcement_status_id: int | None
    ) -> str:
        lot_mapping = {
            110: "Проект", 120: "На рассмотрении", 220: "Опубликован (приём заявок)",
            240: "Опубликован (приём ценовых предложений)",
            360: "Закупка состоялась", 370: "Закупка не состоялась", 410: "Отказ от закупки",
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
    def _as_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [value]

    @staticmethod
    def _region_from_kato(kato_code: str | None) -> str | None:
        if not kato_code or len(kato_code) < 2:
            return None
        regions = {
            "10": "область Абай", "11": "Акмолинская область",
            "15": "Актюбинская область", "19": "Алматинская область",
            "23": "Атырауская область", "27": "Западно-Казахстанская область",
            "31": "Жамбылская область", "33": "область Жетысу",
            "35": "Карагандинская область", "39": "Костанайская область",
            "43": "Кызылординская область", "47": "Мангистауская область",
            "55": "Павлодарская область", "59": "Северо-Казахстанская область",
            "61": "Туркестанская область", "62": "область Улытау",
            "63": "Восточно-Казахстанская область", "71": "Астана",
            "75": "Алматы", "79": "Шымкент",
        }
        return regions.get(kato_code[:2])

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

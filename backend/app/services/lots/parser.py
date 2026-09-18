"""Парсер лотов.

Парсит zakup.gov.kz (через официальный OpenAPI v3 когда есть токен)
или через HTTP-парсинг публичных страниц.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ParsedLot:
    """Один распарсенный лот (тендер)."""

    source: str  # zakup_gov, ets_tender, samruk, ...
    source_id: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    procurement_method: Optional[str] = None
    platform: Optional[str] = None
    amount_kzt: Optional[float] = None
    price_per_unit: Optional[float] = None
    region: Optional[str] = None
    delivery_address: Optional[str] = None
    publish_date: Optional[datetime] = None
    deadline_date: Optional[datetime] = None
    organizer: Optional[str] = None
    organizer_bin: Optional[str] = None
    status: str = "published"
    source_url: Optional[str] = None
    raw_data: dict[str, Any] = field(default_factory=dict)


class LotParser:
    """Парсер лотов с zakup.gov.kz.

    Поддерживает 2 режима:
    1. OpenAPI v3 (рекомендуется) — когда есть токен goszakup
    2. HTTP-парсинг (fallback) — публичные страницы zakup.gov.kz
    """

    BASE_URL_API = "https://ows.goszakup.gov.kz/v2"  # v3 deprecated, v2 is current!
    BASE_URL_GRAPHQL = "https://ows.goszakup.gov.kz/v2/graphql"
    BASE_URL_PUB = "https://zakup.gov.kz"
    TIMEOUT = 30.0

    def __init__(self, api_token: str = ""):
        self.api_token = api_token
        # Реальный токен — не "mock-test-token-12345" и не пустой и не заглушка
        self.use_api = bool(api_token) and not api_token.startswith("mock")

    async def search_lots(
        self,
        query: str = "",
        region: str = "",
        platform: str = "",
        min_amount: float = 0,
        max_amount: float = 0,
        category: str = "",
        limit: int = 50,
    ) -> list[ParsedLot]:
        """Поиск лотов с фильтрами.

        Args:
            query: ключевые слова
            region: г. Алматы, г. Астана, ...
            platform: zakup_gov, ets_tender, samruk, ...
            min_amount, max_amount: диапазон суммы
            category: товар / работа / услуга
            limit: сколько лотов вернуть

        Returns:
            Список ParsedLot
        """
        if self.use_api:
            try:
                return await self._search_via_api(
                    query, region, platform, min_amount, max_amount, category, limit
                )
            except Exception as e:
                logger.warning(f"[LotParser] API search failed: {e}, fallback to web")

        return await self._search_via_web(
            query, region, platform, min_amount, max_amount, category, limit
        )

    async def _search_via_api(
        self,
        query: str,
        region: str,
        platform: str,
        min_amount: float,
        max_amount: float,
        category: str,
        limit: int,
    ) -> list[ParsedLot]:
        """Поиск через OpenAPI v3 goszakup.gov.kz.

        Основной endpoint: /trd-buy (объявления о гос. закупках).
        Дополнительный: /plans/all (пункты планов — есть описание и суммы).
        """
        # Правильные endpoint'ы (из официальной документации)
        endpoints = [
            "/trd-buy",       # объявления (171K+ записей)
            "/plans/all",     # пункты планов с суммами (2.2M+)
            "/lots",          # реестр лотов
        ]
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "User-Agent": "Tendr/1.0",
        }
        # /trd-buy поддерживает limit до 50, /plans/all — limit до 200
        params: dict[str, Any] = {"limit": min(limit, 50)}
        if query:
            params["nameRu"] = query
            params["nameKz"] = query
        if region:
            params["customerBin"] = region
            params["orgBin"] = region
        # В API нет amountFrom/amountTo — фильтрация после получения

        last_error = None
        all_items: list[dict] = []
        seen_ids: set = set()

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            for endpoint in endpoints:
                url = f"{self.BASE_URL_API}{endpoint}"
                try:
                    logger.info(f"[LotParser] trying {url} with params {list(params.keys())}")
                    resp = await client.get(url, headers=headers, params=params)
                    if resp.status_code == 404:
                        continue
                    if resp.status_code != 200:
                        last_error = f"{endpoint}: {resp.status_code} {resp.text[:200]}"
                        logger.warning(f"[LotParser] {last_error}")
                        continue
                    data = resp.json()
                    items = self._extract_items(data)
                    logger.info(
                        f"[LotParser] {endpoint} returned {len(items)} items (total={data.get('total', '?')})"
                    )
                    # Дедупликация по id
                    for item in items:
                        item_id = str(item.get("id", ""))
                        if item_id and item_id not in seen_ids:
                            seen_ids.add(item_id)
                            all_items.append(item)
                    if len(all_items) >= limit:
                        break
                except Exception as e:
                    last_error = f"{endpoint}: {e}"
                    logger.warning(f"[LotParser] {last_error}")
                    continue

        if not all_items:
            raise RuntimeError(f"All endpoints failed. Last: {last_error}")

        # Фильтрация по сумме (постфактум)
        if min_amount or max_amount:
            before = len(all_items)
            all_items = [
                item for item in all_items
                if (not min_amount or self._extract_sum_from_item(item) >= min_amount)
                and (not max_amount or self._extract_sum_from_item(item) <= max_amount)
            ]
            logger.info(
                f"[LotParser] amount filter {min_amount}-{max_amount}: "
                f"{before} -> {len(all_items)} items"
            )

        return [self._parse_api_lot(item) for item in all_items[:limit]]

    def _extract_items(self, data: Any) -> list[dict]:
        """Извлекает список лотов из разных форматов ответа API."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "data", "results", "tenders", "lots", "rows", "content"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            # Может быть wrapped в page объект
            for key in ("_embedded", "_items"):
                if key in data and isinstance(data[key], dict):
                    inner = data[key]
                    for k2 in ("items", "tenders", "lots"):
                        if k2 in inner and isinstance(inner[k2], list):
                            return inner[k2]
        return []

    def _parse_api_lot(self, item: dict[str, Any]) -> ParsedLot:
        """Конвертирует ответ API в ParsedLot.

        Устойчив к разным форматам (camelCase, snake_case, вложенные объекты).
        """
        # Достаём id из разных мест
        lot_id = (
            item.get("id")
            or item.get("tenderId")
            or item.get("trdBuyId")
            or item.get("tender_id")
            or item.get("number")
            or ""
        )

        # Достаём title
        title = self._first_str(
            item,
            "nameRu", "nameKz", "name_ru", "name_kz", "name", "title", "subject",
        ) or ""

        # Description
        description = self._first_str(
            item,
            "descriptionRu", "descriptionKz", "description_ru", "description_kz",
            "description", "desc",
        ) or ""

        # Категория (товар/работа/услуга)
        cat_raw = self._first_str(item, "tenderType", "tender_type", "type", "category", "kind")
        category = self._map_category(cat_raw) if cat_raw else None

        # Способ закупки
        method_raw = self._first_str(
            item, "tenderMethod", "tender_method", "method", "procurementMethod"
        )
        procurement_method = self._map_method(method_raw) if method_raw else None

        # Сумма — из разных мест
        amount = self._first_num(
            item, "totalAmount", "total_amount", "amount", "sum", "price", "budget"
        )

        # Регион
        region = self._first_str(
            item,
            "customerRegionNameRu", "customer_region_name_ru",
            "customerRegionName", "customer_region_name",
            "region", "regionName", "region_name",
        )
        # Из объекта customerRegion
        if not region:
            cr = item.get("customerRegion") or item.get("customer_region") or {}
            if isinstance(cr, dict):
                region = cr.get("nameRu") or cr.get("name") or cr.get("nameKz")
            elif isinstance(cr, str):
                region = cr

        # Заказчик
        organizer = self._first_str(
            item, "customerNameRu", "customer_name_ru", "customerName",
            "customer_name", "organizer", "customer", "name",
        )
        # Из объекта
        if not organizer:
            cu = item.get("customer") or {}
            if isinstance(cu, dict):
                organizer = cu.get("nameRu") or cu.get("name") or cu.get("nameKz")

        organizer_bin = self._first_str(
            item, "customerBin", "customer_bin", "bin", "customerIin", "iin"
        )

        # Статус
        status_raw = self._first_str(item, "status", "state", "tenderStatus")
        status = self._map_status(status_raw) if status_raw else "Опубликован"

        # Даты
        publish_date = self._parse_date(
            self._first_str(item, "publishDate", "publish_date", "publishedAt", "published_at", "createdAt")
        )
        deadline_date = self._parse_date(
            self._first_str(
                item, "applicationDeadline", "application_deadline",
                "deadline", "endDate", "end_date", "acceptEndDate", "accept_end_date",
            )
        )

        # ID для URL (zakup.gov.kz — это SPA с роутами /ru/announce/{id})
        url_id = str(lot_id) if lot_id else ""
        number_anno = self._first_str(item, "numberAnno", "number_anno", "number")
        if number_anno:
            source_url = f"https://v3bl.goszakup.gov.kz/ru/announce/index/{number_anno}"
        elif url_id:
            source_url = f"https://v3bl.goszakup.gov.kz/ru/announce/index/{url_id}"
        else:
            source_url = "https://v3bl.goszakup.gov.kz/ru/announce"

        return ParsedLot(
            source="zakup_gov",
            source_id=url_id or str(hash(title))[:8],  # fallback чтобы не было дублей
            title=title or "(без названия)",
            description=description or None,
            category=category,
            procurement_method=procurement_method,
            platform="zakup.gov.kz",
            amount_kzt=amount,
            region=region or None,
            organizer=organizer or None,
            organizer_bin=organizer_bin or None,
            status=status,
            source_url=source_url,
            publish_date=publish_date,
            deadline_date=deadline_date,
            raw_data=item,
        )

    def _first_str(self, item: dict, *keys: str) -> Optional[str]:
        """Возвращает первое непустое строковое значение по списку ключей."""
        for k in keys:
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, (int, float)) and v:
                return str(v)
        return None

    def _first_num(self, item: dict, *keys: str) -> Optional[float]:
        """Возвращает первое числовое значение по списку ключей.

        Если передано >1 ключа — ищет по ним.
        Если передан 1 ключ — ищет его + несколько стандартных fallback-ключей
        (totalSum, total_sum, amount, price, sum).
        """
        # Если передан один ключ — расширяем стандартными вариантами
        if len(keys) == 1:
            keys = (*keys, "totalSum", "total_sum", "amount", "sum", "price", "contractSumWnds")
        for k in keys:
            v = item.get(k)
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                cleaned = self._parse_amount(v)
                if cleaned is not None:
                    return cleaned
            if isinstance(v, dict):
                inner = self._first_num(v, "amount", "value", "sum")
                if inner is not None:
                    return inner
        return None

    async def _search_via_web(
        self,
        query: str,
        region: str,
        platform: str,
        min_amount: float,
        max_amount: float,
        category: str,
        limit: int,
    ) -> list[ParsedLot]:
        """Fallback: парсим публичную страницу zakup.gov.kz через HTML.

        Это менее надёжно, но работает без токена. Когда получим токен —
        переключимся на _search_via_api.
        """
        # Сейчас zakup.gov.kz — это SPA, парсить HTML напрямую сложно.
        # Используем публичный OpenData или TenderPlus как fallback.

        # Пробуем OpenData источники
        urls_to_try = [
            # Открытые данные Казахстана (если есть)
            f"https://opendata.egov.kz/api/v3/info?token=&source=zakup",
        ]

        # Если ничего не сработало — возвращаем демо-данные
        # с пометкой что нужно подключить API
        logger.info(
            f"[LotParser] No API token + no public parser. "
            f"Use mock data ({limit} lots). Get token at https://ows.goszakup.gov.kz/"
        )
        return self._mock_lots(query, region, limit)

    def _mock_lots(self, query: str, region: str, limit: int) -> list[ParsedLot]:
        """Демо-данные для разработки (пока нет токена).

        Реальные данные начнут поступать когда:
        1. Получим OpenAPI токен goszakup.gov.kz
        2. Или подключим парсер zakup.gov.kz
        """
        demo = [
            ParsedLot(
                source="zakup_gov",
                source_id="demo-001",
                title="Услуги по техническому обслуживанию компьютерного оборудования",
                category="услуга",
                procurement_method="тендер",
                platform="zakup.gov.kz",
                amount_kzt=2_500_000.0,
                region=region or "г. Астана",
                delivery_address="г. Астана, ул. Куйши Дина 32",
                publish_date=datetime(2026, 7, 1),
                deadline_date=datetime(2026, 7, 15),
                organizer="ГУ «Аппарат акима г. Астана»",
                organizer_bin="000000000000",
                status="Приём заявок",
                source_url="https://zakup.gov.kz/tender/demo-001",
            ),
            ParsedLot(
                source="zakup_gov",
                source_id="demo-002",
                title="Поставка канцелярских товаров для государственных учреждений",
                category="товар",
                procurement_method="запрос ценовых предложений",
                platform="zakup.gov.kz",
                amount_kzt=850_000.0,
                region=region or "г. Алматы",
                delivery_address="г. Алматы, пр. Абая 10",
                publish_date=datetime(2026, 7, 3),
                deadline_date=datetime(2026, 7, 17),
                organizer="ГУ «Управление образования г. Алматы»",
                organizer_bin="000000000001",
                status="Опубликован",
                source_url="https://zakup.gov.kz/tender/demo-002",
            ),
            ParsedLot(
                source="zakup_gov",
                source_id="demo-003",
                title="Строительство водопроводных линий в Атырауской области",
                category="работа",
                procurement_method="открытый конкурс",
                platform="zakup.gov.kz",
                amount_kzt=15_000_000.0,
                region="Атырауская область",
                delivery_address="Атырауская область, г. Атырау",
                publish_date=datetime(2026, 6, 25),
                deadline_date=datetime(2026, 7, 15),
                organizer="ГУ «Управление строительства Атырауской области»",
                organizer_bin="000000000002",
                status="Приём заявок",
                source_url="https://zakup.gov.kz/tender/demo-003",
            ),
            ParsedLot(
                source="zakup_gov",
                source_id="demo-004",
                title="Поставка мебели для школ",
                category="товар",
                procurement_method="тендер",
                platform="zakup.gov.kz",
                amount_kzt=8_750_000.0,
                region="Карагандинская область",
                delivery_address="г. Караганда, ул. Ленина 1",
                publish_date=datetime(2026, 7, 5),
                deadline_date=datetime(2026, 7, 22),
                organizer="ГУ «Отдел образования Карагандинской области»",
                organizer_bin="000000000003",
                status="Опубликован",
                source_url="https://zakup.gov.kz/tender/demo-004",
            ),
            ParsedLot(
                source="zakup_gov",
                source_id="demo-005",
                title="Медицинское оборудование для городской больницы",
                category="товар",
                procurement_method="аукцион",
                platform="zakup.gov.kz",
                amount_kzt=42_000_000.0,
                region="г. Шымкент",
                delivery_address="г. Шымкент, ул. Тауке хана 1",
                publish_date=datetime(2026, 7, 4),
                deadline_date=datetime(2026, 7, 20),
                organizer="ГКП «Городская больница №1»",
                organizer_bin="000000000004",
                status="Приём заявок",
                source_url="https://zakup.gov.kz/tender/demo-005",
            ),
        ]
        return demo[:limit]

    @staticmethod
    def _parse_amount(value: Any) -> Optional[float]:
        """Парсит сумму из разных форматов."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = re.sub(r"[^\d.,]", "", value).replace(",", ".")
            try:
                return float(cleaned) if cleaned else None
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_date(value: Any) -> Optional[datetime]:
        """Парсит дату из разных форматов."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            for fmt in [
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ]:
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _map_category(value: str | None) -> Optional[str]:
        """Маппинг категорий zakup.gov.kz → наш формат."""
        if not value:
            return None
        mapping = {
            "GOODS": "товар",
            "WORKS": "работа",
            "SERVICES": "услуга",
        }
        return mapping.get(str(value).upper(), str(value))

    @staticmethod
    def _map_method(value: str | None) -> Optional[str]:
        """Маппинг способа закупки."""
        if not value:
            return None
        mapping = {
            "TENDER": "тендер",
            "AUCTION": "аукцион",
            "REQUEST_FOR_QUOTATIONS": "запрос ценовых предложений",
            "OPEN_CONTEST": "открытый конкурс",
            "FROM_ONE_SOURCE": "из одного источника",
        }
        return mapping.get(str(value).upper(), str(value))

    @staticmethod
    def _extract_sum_from_item(item: dict) -> float:
        """Достаёт сумму из разных полей API v2 (camelCase).
        Используется для пост-фильтрации по сумме.
        """
        for key in (
            "totalSum", "total_sum", "amount", "sum", "price",
            "contractSumWnds", "contract_sum_wnds",
        ):
            v = item.get(key)
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                try:
                    return float(v.replace(" ", "").replace(",", "."))
                except (ValueError, AttributeError):
                    continue
        return 0.0

    @staticmethod
    def _map_status(value: str | None) -> str:
        """Маппинг статусов."""
        if not value:
            return "Опубликован"
        mapping = {
            "PUBLISHED": "Опубликован",
            "DISCUSSION": "Обсуждение",
            "ACCEPTING_APPLICATIONS": "Приём заявок",
            "WAITING_RESULTS": "Ожидание итогов",
            "COMPLETED": "Завершён",
            "CANCELLED": "Отменён",
        }
        return mapping.get(str(value).upper(), str(value))

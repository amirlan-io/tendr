"""Парсер лотов с goszakup.gov.kz.

Два режима:
1. Через официальный API (когда появится токен) — `fetch_lot_via_api()`.
2. Через HTML-парсинг страницы лота (fallback) — `fetch_lot_html()`.

Результат в обоих случаях — единый `ParsedLot`.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from app.core.config import get_settings


class LotNotFoundError(Exception):
    """Лот с таким ID не существует на goszakup.gov.kz."""

    def __init__(self, lot_id: str) -> None:
        self.lot_id = lot_id
        super().__init__(f"Лот с ID {lot_id} не найден на goszakup.gov.kz")


class GoszakupReferenceField(str, enum.Enum):
    ANNOUNCEMENT_ID = "announcement_id"
    ANNOUNCEMENT_NUMBER = "announcement_number"
    LOT_ID = "lot_id"
    LOT_NUMBER = "lot_number"


@dataclass(frozen=True, slots=True)
class GoszakupReference:
    """Canonical Goszakup reference information."""

    raw: str
    kind: GoszakupReferenceField
    announcement_id: str | None = None
    announcement_number: str | None = None
    lot_id: str | None = None
    lot_number: str | None = None
    source_url: str | None = None
    host: str | None = None


@dataclass
class ParsedLot:
    lot_id: str
    title: str
    customer_name: str
    customer_bin: str | None
    method: str
    deadline: str | None
    budget_kzt: float | None
    description: str
    technical_specification: str
    requirements: list[str] = field(default_factory=list)
    documents_required: list[str] = field(default_factory=list)
    raw_html: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class GoszakupParser:
    """Парсер сайта/API госзакупок РК."""

    def __init__(self) -> None:
        s = get_settings()
        self._api_url = s.goszakup_api_url.rstrip("/")
        self._api_token = s.goszakup_api_token or None
        # Определяем версию API по префиксу базового URL
        # v3: /v3 (default) → эндпоинт /v3/lots/{id}
        # v2: /v2 → эндпоинт /v2/trd-buy/{id} (lot-specific endpoint отсутствует)
        self._api_version = "v3" if self._api_url.endswith("/v3") else "v2"
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "TendrBot/0.1 (+https://tendr.kz)"},
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_lot(self, lot_id_or_url: str) -> ParsedLot:
        """Универсальный метод: принимает lot_number, announcement_number, lot_id или полный URL."""
        reference = self.parse_reference(lot_id_or_url)
        lookup_key = reference.lot_number or reference.announcement_number or reference.lot_id or reference.announcement_id
        if lookup_key and ("-" in str(lookup_key) or str(lookup_key).startswith("0")):
            resolved = await self.lookup_lot_number(reference)
            lookup_key = resolved.lot_id or resolved.announcement_id or reference.lot_number or reference.announcement_number

        if self._api_token:
            try:
                parsed = await self._fetch_lot_via_api(str(lookup_key))
            except Exception as e:
                logger.warning("API fetch failed for {}, fallback to HTML: {}", lookup_key, e)
            else:
                # Каноническая ссылка вычислена из входного reference — на
                # GraphQL-пути её больше негде взять, а без неё UI не может
                # дать переход на исходное объявление.
                _attach_source_url(parsed, reference)
                return parsed
        parsed = await self._fetch_lot_html(str(lookup_key))
        _attach_source_url(parsed, reference)
        return parsed

    @staticmethod
    def parse_reference(value: str) -> GoszakupReference:
        """Normalize a Goszakup reference without stripping the lot suffix."""
        text = (value or "").strip()
        if not text:
            raise ValueError("Пустая ссылка на Goszakup")

        if re.fullmatch(r"\d{6,}(?:-\d+)?", text):
            match = re.fullmatch(r"(\d{6,})(?:-(\d+))?", text)
            if not match:
                raise ValueError("Некорректный ID лота goszakup")
            if match.group(2):
                lot_number = match.group(0)
                return GoszakupReference(
                    raw=text,
                    kind=GoszakupReferenceField.LOT_NUMBER,
                    lot_number=lot_number,
                    source_url=f"https://goszakup.gov.kz/ru/announce/index/{lot_number}",
                    host="goszakup.gov.kz",
                )
            announcement_id = match.group(1)
            return GoszakupReference(
                raw=text,
                kind=GoszakupReferenceField.ANNOUNCEMENT_ID,
                announcement_id=announcement_id,
                source_url=f"https://goszakup.gov.kz/ru/announce/index/{announcement_id}",
                host="goszakup.gov.kz",
            )

        parsed = urlsplit(text)
        if parsed.username or parsed.password:
            raise ValueError("Ссылка goszakup содержит userinfo")
        if parsed.fragment:
            raise ValueError("Ссылка goszakup не должна содержать fragment")
        if parsed.scheme.lower() != "https":
            raise ValueError("Поддерживаются только HTTPS-ссылки goszakup.gov.kz")
        if parsed.netloc and parsed.port not in (None, 443):
            raise ValueError("Ссылки goszakup.gov.kz не должны содержать нестандартный порт")

        host = (parsed.hostname or "").lower()
        allowed_hosts = {
            "goszakup.gov.kz",
            "www.goszakup.gov.kz",
            "ows.goszakup.gov.kz",
            "v3bl.goszakup.gov.kz",
        }
        if not host or host not in allowed_hosts:
            raise ValueError("Поддерживаются только ссылки goszakup.gov.kz")
        if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
            raise ValueError("Локальный адрес не поддерживается")
        if re.fullmatch(r"\d+(?:\.\d+){3}", host):
            raise ValueError("IP-адрес не поддерживается")
        if not parsed.path or parsed.path == "/":
            raise ValueError("Неизвестный URL pattern для goszakup")
        if parsed.query:
            raise ValueError("Запросы в ссылке goszakup не поддерживаются")

        path_pattern = re.compile(r"/(?:ru|kk)/(?:announce|lot|view)/(?:index|show)/.*", re.IGNORECASE)
        if not path_pattern.match(parsed.path):
            raise ValueError("Неизвестный URL pattern для goszakup")

        match = re.search(r"(\d{6,}(?:-\d+)?)", parsed.path or "")
        if not match:
            raise ValueError("Неизвестный URL pattern для goszakup")

        candidate = match.group(1)
        if "-" in candidate:
            kind = GoszakupReferenceField.LOT_NUMBER
            lot_number = candidate
            source_url = f"https://{host}/ru/announce/index/{lot_number}"
            return GoszakupReference(
                raw=text,
                kind=kind,
                lot_number=lot_number,
                source_url=source_url,
                host=host,
            )

        kind = GoszakupReferenceField.ANNOUNCEMENT_ID
        source_url = f"https://{host}/ru/announce/index/{candidate}"
        return GoszakupReference(
            raw=text,
            kind=kind,
            announcement_id=candidate,
            source_url=source_url,
            host=host,
        )

    @staticmethod
    def _normalize_reference(value: str) -> str:
        """Возвращает полный lot_number без потери суффикса."""
        return GoszakupParser.parse_reference(value).lot_number or ""

    @staticmethod
    def _extract_lot_id(value: str) -> str:
        """Возвращает lot_number как есть, без обрезания суффикса."""
        ref = GoszakupParser.parse_reference(value)
        return ref.lot_number or ref.announcement_id or ""

    async def lookup_lot_number(self, reference: GoszakupReference) -> GoszakupReference:
        """Lookup по полному lot_number, без обрезки суффикса и без строковой интерполяции в GraphQL query."""
        if not reference.lot_number:
            raise ValueError("lot_number отсутствует в ссылке")
        if not self._api_token:
            raise ValueError("API токен goszakup не настроен для lookup по lot_number")

        query = """
        query LookupLotNumber($lot_number: String!) {
          trd_buy(filters: { number_anno: $lot_number }, limit: 1) {
            id
            number_anno
          }
          lots(filters: { lot_number: $lot_number }, limit: 10) {
            id
            lot_number
            trd_buy_id
          }
        }
        """
        variables = {"lot_number": reference.lot_number}
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        graphql_url = f"{self._api_url.rstrip('/')}/graphql"
        try:
            response = await self._client.post(
                graphql_url,
                headers=headers,
                json={"query": query, "variables": variables},
                timeout=15.0,
                follow_redirects=False,
            )
        except TypeError:
            response = await self._client.post(
                graphql_url,
                headers=headers,
                json={"query": query, "variables": variables},
                timeout=15.0,
            )
        except httpx.TimeoutException as exc:
            raise ValueError("Timeout при lookup lot_number в Goszakup API") from exc
        except httpx.HTTPError as exc:
            raise ValueError("Сетевая ошибка при lookup lot_number в Goszakup API") from exc

        if response.status_code in {301, 302, 303, 307, 308}:
            raise ValueError("Получен redirect при lookup lot_number в Goszakup API")
        if response.status_code != 200:
            raise ValueError("API lookup по lot_number недоступен в текущей конфигурации")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("Повреждённый JSON-ответ при lookup lot_number в Goszakup API") from exc

        errors = payload.get("errors")
        if errors:
            raise ValueError("API не поддерживает lookup по lot_number или вернул ошибку")

        data = payload.get("data") or {}
        trd_buy_items = data.get("trd_buy") or []
        lot_items = data.get("lots") or []
        if not trd_buy_items and not lot_items:
            raise ValueError("Не удалось найти лот по full lot_number в Goszakup API")

        trd_buy = trd_buy_items[0] if trd_buy_items else {}
        lot_item = lot_items[0] if lot_items else {}
        actual_trd_buy_id = trd_buy.get("id") or lot_item.get("trd_buy_id") or lot_item.get("trdBuyId")
        actual_lot_id = lot_item.get("id") or lot_item.get("lot_id")
        if actual_trd_buy_id is None and actual_lot_id is None:
            raise ValueError("API lookup не вернул фактический trd_buy_id/lot_id")

        return GoszakupReference(
            raw=reference.raw,
            kind=reference.kind,
            announcement_id=str(actual_trd_buy_id) if actual_trd_buy_id is not None else None,
            lot_id=str(actual_lot_id) if actual_lot_id is not None else None,
            lot_number=reference.lot_number,
            source_url=reference.source_url,
            host=reference.host,
        )

    async def _fetch_lot_via_api(self, lot_id: str) -> ParsedLot:
        """Запрос к OWS goszakup.gov.kz (нужен токен).

        Стратегия:
        1. Сначала пробуем GraphQL с вложенными Lots — даёт наиболее полные
           данные (имена позиций, description_ru, amount, count, customer_bin).
        2. Если GraphQL не сработал — REST endpoint (v3/lots/{id} или v2/trd-buy/{id}).
        3. Если и REST не сработал — fallback на HTML-парсинг.

        GraphQL предпочтителен потому что:
        - v2 REST /trd-buy/{id} НЕ возвращает technical_specification_ru
          (только базовые поля объявления: name_ru, total_sum, org_bin, end_date)
        - GraphQL позволяет одним запросом получить TrdBuy + Lots + Organizer
          (а REST требует отдельных запросов на каждый ресурс).
        """
        if not self._api_token:
            # Без токена — fallback на HTML
            logger.info("No API token, falling back to HTML for lot {}", lot_id)
            return await self._fetch_lot_html(lot_id)

        # 1) Пробуем GraphQL — самый полный источник
        try:
            result = await self._fetch_lot_via_graphql(lot_id)
            if result is not None:
                return result
            logger.info("GraphQL returned no data for lot {}, fallback to REST", lot_id)
        except LotNotFoundError:
            raise
        except Exception as e:
            logger.warning("GraphQL fetch failed for {}, fallback to REST: {}", lot_id, e)

        # 2) REST fallback
        # v3: /v3/lots/{id} — детальная карточка лота с ТЗ
        # v2: /v2/trd-buy/{id} — карточка объявления с базовыми полями (ТЗ отсутствует)
        if self._api_version == "v3":
            primary_url = f"{self._api_url}/lots/{lot_id}"
        else:
            primary_url = f"{self._api_url}/trd-buy/{lot_id}"

        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Accept": "application/json",
        }
        try:
            resp = await self._client.get(primary_url, headers=headers, timeout=20.0)
        except Exception as e:
            logger.warning("API request failed for {}: {}. Falling back to HTML.", lot_id, e)
            return await self._fetch_lot_html(lot_id)

        if resp.status_code == 404:
            raise LotNotFoundError(lot_id)
        if resp.status_code != 200:
            logger.warning(
                "API returned {} for {}. Falling back to HTML.", resp.status_code, lot_id
            )
            return await self._fetch_lot_html(lot_id)

        try:
            data = resp.json()
        except Exception as e:
            logger.warning("Failed to parse API JSON: {}. Falling back to HTML.", e)
            return await self._fetch_lot_html(lot_id)

        # Если в данных нет customer_name — подтягиваем заказчика по org_bin через GraphQL
        # (важно для v2 API: /v2/trd-buy возвращает только org_bin без имени)
        if not data.get("customer_name") and not data.get("nameRu"):
            org_bin = data.get("org_bin") or data.get("orgBin") or data.get("customer_bin")
            if org_bin and self._api_token:
                try:
                    subject = await self._fetch_subject_by_bin(org_bin)
                    if subject:
                        # Раскладываем имя в поля, которые умеет читать _map_api_response_to_lot
                        name_ru = subject.get("nameRu") or subject.get("name_ru")
                        if name_ru:
                            data.setdefault("customer_name", name_ru)
                            data.setdefault("customer", {})["name_ru"] = name_ru
                            data.setdefault("customer", {})["nameRu"] = name_ru
                            logger.info(
                                "Resolved customer name via GraphQL Subjects for bin={}: {}",
                                org_bin, name_ru[:60]
                            )
                except Exception as e:
                    logger.debug("Subject lookup failed for bin {}: {}", org_bin, e)

        # Маппинг JSON → ParsedLot (мягкий, устойчив к отсутствию полей)
        try:
            return self._map_api_response_to_lot(data, lot_id)
        except Exception as e:
            logger.error("API response mapping failed: {}", e)
            return await self._fetch_lot_html(lot_id)

    async def _fetch_lot_via_graphql(self, lot_id: str) -> ParsedLot | None:
        """Получить лот через GraphQL с вложенными Lots и Organizer.

        GraphQL endpoint: https://ows.goszakup.gov.kz/v2/graphql
        Схема поддерживает фильтр `trd_buy(filters: {id: [Int!]!}, limit, after)`.

        Возвращает ParsedLot или None если лот не найден.
        Поднимает LotNotFoundError если GraphQL подтвердил отсутствие лота.

        Важная особенность схемы: вложенные поля `lots` и `organizer` в TrdBuy
        почти всегда возвращаются пустыми — поэтому делаем отдельные root-запросы
        к `lots(filters: {trd_buy_id: ...})` и `subjects(filters: {bin: ...})`.
        """
        try:
            lot_id_int = int(lot_id)
        except (TypeError, ValueError):
            # Если lot_id не числовой — GraphQL не сработает
            return None

        # 1. Получаем TrdBuy (объявление)
        query_trd = """
        query GetTrdBuy($id: [Int!]) {
          trd_buy(filters: {id: $id}, limit: 1) {
            id
            number_anno
            name_ru
            name_kz
            total_sum
            count_lots
            ref_trade_methods_id
            ref_buy_status_id
            org_bin
            customer_bin
            start_date
            end_date
            publish_date
            discus_start_date
            discus_end_date
            ref_trade_methods { id name_ru name_kz }
            ref_buy_status { id name_ru name_kz }
          }
        }
        """
        url = "https://ows.goszakup.gov.kz/v2/graphql"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            resp = await self._client.post(
                url,
                headers=headers,
                json={"query": query_trd, "variables": {"id": [lot_id_int]}},
                timeout=15.0,
            )
        except Exception as e:
            logger.warning("GraphQL request failed for {}: {}", lot_id, e)
            return None

        if resp.status_code != 200:
            logger.warning("GraphQL returned {} for {}", resp.status_code, lot_id)
            return None

        try:
            payload = resp.json()
        except Exception as e:
            logger.warning("GraphQL JSON parse failed: {}", e)
            return None

        if "errors" in payload:
            errors = payload["errors"]
            logger.warning("GraphQL errors for {}: {}", lot_id, errors[:1])
            return None

        trd_buy_list = (payload.get("data") or {}).get("trd_buy") or []
        if not trd_buy_list:
            # GraphQL подтвердил — лота с таким ID нет
            raise LotNotFoundError(lot_id)

        trd = trd_buy_list[0]

        # 2. Получаем Lots (позиции лота) — отдельный root-запрос
        lots: list[dict] = []
        try:
            lots = await self._fetch_lots_via_graphql(lot_id_int)
        except Exception as e:
            logger.warning("Failed to fetch Lots for trd_buy {}: {}", lot_id_int, e)

        trd["lots"] = lots

        # 3. Получаем профиль заказчика (Subject) по org_bin
        org_bin = trd.get("org_bin") or trd.get("customer_bin")
        if org_bin:
            try:
                subject = await self._fetch_subject_by_bin(org_bin)
                if subject:
                    trd["organizer"] = subject
            except Exception as e:
                logger.debug("Subject lookup failed for bin {}: {}", org_bin, e)

        # 4. Получаем план закупок (PlnPoint) для каждой позиции — это даёт
        # детальную информацию: цена за единицу, срок поставки, код продукции
        # (ref_enstru_code), полное описание из плана (desc_ru + extra_desc_ru).
        for lot in lots:
            point_list = lot.get("point_list") or []
            if not point_list:
                continue
            try:
                pln_points = await self._fetch_pln_points_via_graphql(point_list)
                if pln_points:
                    lot["plans"] = pln_points[0] if pln_points else None
                    lot["all_plans"] = pln_points
            except Exception as e:
                logger.debug("PlnPoint lookup failed for lot {}: {}", lot.get("id"), e)

        # 5. Дополняем данными из v3/trd-buy/{id} REST endpoint — там есть
        # дополнительные поля (kato, fin_year, supplier, parent_id и т.д.),
        # которых нет в GraphQL.
        try:
            v3_data = await self._fetch_trd_buy_via_rest_v3(lot_id)
            if v3_data:
                trd["_v3_extra"] = v3_data
        except Exception as e:
            logger.debug("v3 REST fetch failed for {}: {}", lot_id, e)

        return self._map_graphql_response_to_lot(trd, lot_id)

    async def _fetch_pln_points_via_graphql(self, point_ids: list[int]) -> list[dict]:
        """Получить планы закупок (PlnPoint) по списку ID.

        PlnPoint содержит:
        - desc_ru, extra_desc_ru — описание из плана (часто более подробное, чем в Lot)
        - count, price, amount — количество, цена за единицу, общая сумма
        - ref_enstru_code — код продукции в госреестре ЕНС ТРУ
        - supply_date_ru — срок поставки
        - ref_units — единицы измерения (шт., л, кг, и т.д.)
        - customer — заказчик (Subject)
        """
        if not point_ids:
            return []
        query = """
        query GetPlans($id: [Int!]) {
          plans(filters: {id: $id}, limit: 50) {
            id
            rootrecord_id
            subject_biin
            name_ru
            name_kz
            desc_ru
            desc_kz
            extra_desc_ru
            extra_desc_kz
            count
            price
            amount
            ref_enstru_code
            supply_date_ru
            prepayment
            ref_units { name_ru name_kz }
            customer { pid bin name_ru full_name_ru }
            ref_trade_methods { id name_ru }
          }
        }
        """
        url = "https://ows.goszakup.gov.kz/v2/graphql"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        resp = await self._client.post(
            url,
            headers=headers,
            json={"query": query, "variables": {"id": point_ids}},
            timeout=15.0,
        )
        if resp.status_code != 200:
            return []
        try:
            payload = resp.json()
        except Exception:
            return []
        if "errors" in payload:
            return []
        return (payload.get("data") or {}).get("plans") or []

    async def _fetch_trd_buy_via_rest_v3(self, lot_id: str) -> dict | None:
        """Дополнительные поля из REST endpoint /v3/trd-buy/{id}.

        GraphQL возвращает не все поля, которые есть в REST v3:
        - kato (коды КАТО — регион поставки)
        - fin_year (год финансирования)
        - id_supplier / biin_supplier (победитель, если лот завершён)
        - parent_id (родительская закупка — для повторных)
        - ref_type_trade_id, ref_spec_purchase_type_id
        - itogi_date_public (дата публикации итогов)
        """
        url = f"https://ows.goszakup.gov.kz/v3/trd-buy/{lot_id}"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Accept": "application/json",
        }
        try:
            resp = await self._client.get(url, headers=headers, timeout=10.0)
        except Exception as e:
            logger.debug("v3 REST request failed for {}: {}", lot_id, e)
            return None
        if resp.status_code != 200:
            return None
        try:
            return resp.json()
        except Exception:
            return None

    async def _fetch_lots_via_graphql(self, trd_buy_id: int) -> list[dict]:
        """Получить позиции (Lots) для объявления через root-запрос lots.

        GraphQL не отдаёт вложенные lots в TrdBuy, поэтому нужен отдельный запрос.
        Возвращает список словарей с полями: id, lot_number, name_ru, name_kz,
        description_ru, description_kz, amount, count, customer_bin, и т.д.
        """
        # Внимание: фильтр `trd_buy_id` в LotsFiltersInput тоже имеет тип [Int!]
        # (список), поэтому передаём переменную как список.
        query = """
        query GetLots($trd_buy_id: [Int!]) {
          lots(filters: {trd_buy_id: $trd_buy_id}, limit: 50) {
            id
            lot_number
            name_ru
            name_kz
            description_ru
            description_kz
            amount
            count
            customer_bin
            point_list
            dumping
            psd_sign
            compl_exp
            ref_lots_status { id name_ru }
          }
        }
        """
        url = "https://ows.goszakup.gov.kz/v2/graphql"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        resp = await self._client.post(
            url,
            headers=headers,
            json={"query": query, "variables": {"trd_buy_id": [trd_buy_id]}},
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.warning("GraphQL lots returned {} for trd_buy {}", resp.status_code, trd_buy_id)
            return []
        try:
            payload = resp.json()
        except Exception:
            return []
        if "errors" in payload:
            logger.warning("GraphQL lots errors: {}", payload["errors"][:1])
            return []
        return (payload.get("data") or {}).get("lots") or []

    def _map_graphql_response_to_lot(self, t: dict, lot_id: str) -> ParsedLot:
        """Маппинг ответа GraphQL TrdBuy + вложенных Lots → ParsedLot.

        Здесь:
        - title = TrdBuy.name_ru (общее название объявления)
        - если есть Lots — формируем detailed description из позиций
        - technical_specification = composition всех Lots (name + description + count + amount)
        - customer_name = organizer.name_ru (или full_name_ru)
        - customer_bin = org_bin
        - deadline = end_date (ISO datetime строка)
        - budget_kzt = total_sum
        - method = ref_trade_methods.name_ru (если есть) иначе маппинг по ref_trade_methods_id
        """
        # Заголовок объявления
        title = (
            t.get("name_ru")
            or t.get("name_kz")
            or f"Лот {lot_id}"
        )

        # Заказчик
        org = t.get("organizer") or {}
        customer_name = (
            org.get("name_ru")
            or org.get("full_name_ru")
            or t.get("customer_bin")
            or ""
        )
        customer_bin = t.get("org_bin") or t.get("customer_bin") or ""

        # Бюджет и дедлайн
        try:
            budget_kzt = float(t.get("total_sum")) if t.get("total_sum") is not None else None
        except (TypeError, ValueError):
            budget_kzt = None

        deadline = t.get("end_date") or t.get("discus_end_date")

        # Способ закупки
        ref_method_id = t.get("ref_trade_methods_id")
        ref_method_obj = t.get("ref_trade_methods") or {}
        if ref_method_obj.get("name_ru"):
            method = ref_method_obj["name_ru"]
        elif isinstance(ref_method_id, int):
            method_map = {
                1: "электронный аукцион",
                2: "конкурс",
                3: "запрос ценовых предложений",
                7: "аукцион",
                23: "из одного источника",
                118: "через товарные биржи",
            }
            method = method_map.get(ref_method_id, f"метод #{ref_method_id}")
        else:
            method = "other"

        # Статус
        ref_status_obj = t.get("ref_buy_status") or {}
        status = ref_status_obj.get("name_ru") or "Опубликован"

        # Lots — конкретные позиции закупки
        lots = t.get("lots") or []

        # v3 REST extra (kato, fin_year, supplier, и т.д.)
        v3_extra = t.get("_v3_extra") or {}

        # Собираем описание из Lots + Plans (план закупок даёт доп. детали)
        if lots:
            lot_lines = []
            for i, lot in enumerate(lots, 1):
                lot_name = lot.get("name_ru") or lot.get("name_kz") or ""
                lot_desc = lot.get("description_ru") or ""
                lot_amount = lot.get("amount")
                lot_count = lot.get("count")
                lot_unit = ""
                lot_price_per_unit = ""

                # PlnPoint даёт детальную информацию
                plan = lot.get("plans") or {}
                if plan:
                    # Единицы измерения
                    if plan.get("ref_units") and plan["ref_units"].get("name_ru"):
                        lot_unit = f" {plan['ref_units']['name_ru']}"
                    # Цена за единицу
                    try:
                        if plan.get("price") is not None:
                            lot_price_per_unit = f", цена за ед.: {float(plan['price']):,.2f} ₸"
                    except (TypeError, ValueError):
                        pass
                    # Дополнительное описание из плана
                    plan_extra = plan.get("extra_desc_ru") or ""
                    if plan_extra and plan_extra != lot_desc:
                        lot_desc = f"{lot_desc}. {plan_extra}".strip(". ")

                if lot_count is not None:
                    lot_count_str = f", количество: {lot_count}{lot_unit}"
                else:
                    lot_count_str = ""
                lot_price = ""
                if lot_amount is not None:
                    try:
                        lot_price = f", сумма: {float(lot_amount):,.2f} ₸"
                    except (TypeError, ValueError):
                        lot_price = f", сумма: {lot_amount}"
                line = f"Позиция {i}: {lot_name}"
                if lot_desc:
                    line += f" ({lot_desc})"
                line += f"{lot_count_str}{lot_price_per_unit}{lot_price}"
                # Срок поставки из плана
                if plan and plan.get("supply_date_ru"):
                    line += f"\n    Срок поставки: {plan['supply_date_ru']}"
                # Код ЕНС ТРУ
                if plan and plan.get("ref_enstru_code"):
                    line += f"\n    Код ЕНС ТРУ: {plan['ref_enstru_code']}"
                lot_lines.append(line)
            lots_block = "\n".join(lot_lines)
        else:
            lots_block = ""

        # Тех. спецификация — объединяем все доступные текстовые данные
        ts_parts = []
        if title:
            ts_parts.append(f"Предмет закупки: {title}")
        if t.get("name_kz") and t.get("name_kz") != title:
            ts_parts.append(f"Қазақша атауы: {t['name_kz']}")
        if lots_block:
            ts_parts.append(f"\nПозиции лота ({len(lots)} шт.):\n{lots_block}")
        if t.get("number_anno"):
            ts_parts.append(f"Номер объявления: {t['number_anno']}")
        if t.get("count_lots"):
            ts_parts.append(f"Количество позиций: {t['count_lots']}")

        # v3 REST extra — доп. поля
        if v3_extra:
            if v3_extra.get("kato"):
                ts_parts.append(f"КАТО (регион): {', '.join(map(str, v3_extra['kato']))}")
            if v3_extra.get("fin_year"):
                ts_parts.append(f"Год финансирования: {', '.join(map(str, v3_extra['fin_year']))}")
            if v3_extra.get("biin_supplier"):
                ts_parts.append(f"БИН победителя: {v3_extra['biin_supplier']}")
            if v3_extra.get("parent_id"):
                ts_parts.append(f"Родительская закупка: #{v3_extra['parent_id']}")
            if v3_extra.get("itogi_date_public"):
                ts_parts.append(f"Дата публикации итогов: {v3_extra['itogi_date_public']}")

        technical_specification = "\n".join(ts_parts)

        # Описание (для UI — краткое)
        description = lots_block or title

        # Дополнительные поля
        extra = {
            "trd_buy_id": t.get("id"),
            "number_anno": t.get("number_anno"),
            "publish_date": t.get("publish_date"),
            "start_date": t.get("start_date"),
            "end_date": t.get("end_date"),
            "discus_start_date": t.get("discus_start_date"),
            "discus_end_date": t.get("discus_end_date"),
            "ref_trade_methods_id": ref_method_id,
            "ref_buy_status_id": t.get("ref_buy_status_id"),
            "lots_count": len(lots),
            "lots": [
                {
                    "id": lot.get("id"),
                    "lot_number": lot.get("lot_number"),
                    "name_ru": lot.get("name_ru"),
                    "description_ru": lot.get("description_ru"),
                    "amount": lot.get("amount"),
                    "count": lot.get("count"),
                    "customer_bin": lot.get("customer_bin"),
                }
                for lot in lots
            ],
            "source": "graphql_v2",
        }

        return ParsedLot(
            lot_id=str(t.get("id") or lot_id),
            title=title,
            customer_name=customer_name,
            customer_bin=customer_bin or None,
            method=method,
            deadline=deadline,
            budget_kzt=budget_kzt,
            description=description,
            technical_specification=technical_specification,
            extra=extra,
        )

    async def _fetch_subject_by_bin(self, bin_str: str) -> dict | None:
        """Получает профиль заказчика по БИН через GraphQL Subjects.

        Возвращает dict {name_ru, full_name_ru, bin, pid, ...} или None.
        """
        query = (
            '{ subjects(filters: {bin: "' + bin_str + '"}, limit: 1) '
            "{ pid bin name_ru full_name_ru name_kz full_name_kz } }"
        )
        url = "https://ows.goszakup.gov.kz/v2/graphql"
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        resp = await self._client.post(
            url, headers=headers, json={"query": query}, timeout=15.0
        )
        if resp.status_code != 200:
            logger.debug("Subjects GraphQL returned {}", resp.status_code)
            return None
        try:
            payload = resp.json()
        except Exception:
            return None
        if "errors" in payload:
            logger.debug("Subjects GraphQL errors: {}", payload["errors"][:1])
            return None
        subjects = (payload.get("data") or {}).get("subjects") or []
        return subjects[0] if subjects else None

    def _safe_get(self, d: dict, *keys, default: Any = None) -> Any:
        """Безопасное извлечение вложенных полей."""
        cur = d
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
            if cur is None:
                return default
        return cur

    def _map_api_response_to_lot(self, data: dict, lot_id: str) -> ParsedLot:
        """Маппинг ответа OWS API → ParsedLot.

        Поддерживает оба формата:
        - v2: snake_case (name_ru, name_kz, total_sum, org_bin)
        - v3: camelCase (nameRu, nameKk, totalAmount, customerBin)
        """
        # Заголовок (могут быть nameRu, nameKk, name — берём первый непустой)
        title = (
            self._safe_get(data, "name_ru")
            or self._safe_get(data, "nameRu")
            or self._safe_get(data, "name_kz")
            or self._safe_get(data, "nameKk")
            or self._safe_get(data, "name")
            or f"Лот {lot_id}"
        )

        # Заказчик
        customer = (
            self._safe_get(data, "customer_name")
            or self._safe_get(data, "customer", "name_ru")
            or self._safe_get(data, "customer", "nameRu")
            or self._safe_get(data, "customer", "name_kz")
            or self._safe_get(data, "customer", "nameKk")
            or self._safe_get(data, "customer", "name")
            or self._safe_get(data, "customerName")
            or ""
        )
        customer_bin = (
            self._safe_get(data, "org_bin")
            or self._safe_get(data, "customer_bin")
            or self._safe_get(data, "customer", "bin")
            or self._safe_get(data, "customerBin")
            or self._safe_get(data, "customer", "iinBin")
            or ""
        )

        # Описание
        description = (
            self._safe_get(data, "description_ru")
            or self._safe_get(data, "descriptionRu")
            or self._safe_get(data, "description_kz")
            or self._safe_get(data, "descriptionKk")
            or self._safe_get(data, "description")
            or ""
        )

        # Бюджет (v2: total_sum, v3: totalAmount)
        amount = data.get("total_sum") or data.get("totalAmount") or data.get("amount")
        try:
            budget_kzt = float(amount) if amount is not None else None
        except (TypeError, ValueError):
            budget_kzt = None

        # Срок (v2: end_date, v3: endDate/acceptingAt)
        deadline_str = (
            data.get("end_date")
            or data.get("endDate")
            or data.get("acceptingAt")
            or data.get("deadline")
        )

        # Способ закупки (v2: ref_trade_methods_id число, v3: tradeMethods[0].nameRu)
        ref_method_id = data.get("ref_trade_methods_id") or data.get("refTradeMethodsId")
        if isinstance(ref_method_id, int):
            method_map = {1: "open_tender", 2: "open_tender", 3: "request_quotes", 7: "auction", 23: "single_source"}
            method = method_map.get(ref_method_id, f"method_{ref_method_id}")
        else:
            method_name = (
                self._safe_get(data, "tradeMethods", 0, "nameRu")
                or self._safe_get(data, "tradeMethod", "nameRu")
                or data.get("method")
                or "other"
            )
            method_name_lower = method_name.lower()
            if "конкурс" in method_name_lower or "тендер" in method_name_lower:
                method = "tender"
            elif "аукцион" in method_name_lower:
                method = "auction"
            elif "запрос цен" in method_name_lower or "ценов" in method_name_lower:
                method = "request_quotes"
            elif "источник" in method_name_lower:
                method = "single_source"
            else:
                method = "other"

        # ТЗ (v2 не возвращает ТЗ, v3 — да)
        technical_specification = (
            data.get("technical_specification_ru")
            or data.get("technicalSpecificationRu")
            or data.get("desc_ru")
            or data.get("descriptionRu")
            or data.get("extra_desc_ru")
            or data.get("extraDescRu")
            or description
        )

        return ParsedLot(
            lot_id=lot_id,
            title=title,
            customer_name=customer or "",
            customer_bin=customer_bin or None,
            method=method,
            deadline=deadline_str,
            budget_kzt=budget_kzt,
            description=description,
            technical_specification=technical_specification or description,
        )

    async def _fetch_lot_html(self, lot_id: str) -> ParsedLot:
        """HTML-парсинг карточки лота. Структура сайта может меняться,
        поэтому используем эвристики, а не жёсткие селекторы."""
        # Пробуем несколько известных URL-паттернов goszakup.gov.kz
        candidates = [
            f"https://goszakup.gov.kz/ru/announce/index/{lot_id}",
            f"https://goszakup.gov.kz/ru/announce/show/{lot_id}",
            f"https://goszakup.gov.kz/kk/announce/show/{lot_id}",
        ]
        saw_any_404 = False
        last_exc: Exception | None = None
        for url in candidates:
            try:
                resp = await self._client.get(url)
                if resp.status_code == 404:
                    saw_any_404 = True
                    continue
                if resp.status_code == 200 and len(resp.text) > 1000:
                    return self._parse_html(lot_id, resp.text, url)
            except Exception as e:
                last_exc = e
                logger.debug("HTML fetch failed for {}: {}", url, e)
                continue
        # Если все URL вернули 404 — лот реально не существует
        if saw_any_404:
            raise LotNotFoundError(lot_id)
        raise RuntimeError(
            f"Не удалось получить лот {lot_id} ни по одному URL-паттерну. "
            f"Последняя ошибка: {last_exc}"
        )

    def _parse_html(self, lot_id: str, html: str, source_url: str) -> ParsedLot:
        """Эвристический парсинг HTML-страницы лота."""
        soup = BeautifulSoup(html, "lxml")

        # Заголовок лота
        title_el = soup.select_one("h1, .announce-title, [class*='title']")
        title = title_el.get_text(strip=True) if title_el else f"Лот {lot_id}"

        # Заказчик и БИН
        customer_name = ""
        customer_bin = None
        text = soup.get_text("\n", strip=True)

        m = re.search(r"БИН\s*[:#]?\s*(\d{12})", text)
        if m:
            customer_bin = m.group(1)
        m = re.search(r"Заказчик\s*[:\-]?\s*([^\n]{3,200})", text, re.IGNORECASE)
        if m:
            customer_name = m.group(1).strip()

        # Способ закупки
        method = "other"
        for keyword, code in [
            ("конкурс", "tender"),
            ("аукцион", "auction"),
            ("запрос ценовых", "request_quotes"),
            ("из одного источника", "single_source"),
        ]:
            if keyword.lower() in text.lower():
                method = code
                break

        # Бюджет
        budget_kzt: float | None = None
        m = re.search(r"(\d[\d\s]{2,})\s*(тенге|тг)", text, re.IGNORECASE)
        if m:
            try:
                budget_kzt = float(re.sub(r"\s+", "", m.group(1)))
            except ValueError:
                pass

        # Срок приёма заявок
        deadline = None
        m = re.search(
            r"(приём заявок|окончани[ея])\s*[:\-]?\s*(\d{2}[.\-/]\d{2}[.\-/]\d{4})",
            text,
            re.IGNORECASE,
        )
        if m:
            deadline = m.group(2)

        # Техническое задание / описание
        # Ищем крупные блоки с ТЗ
        ts_text = ""
        for tag in soup.find_all(["div", "section"]):
            t = tag.get_text(" ", strip=True)
            if "техническ" in t.lower() and len(t) > 200:
                ts_text = t
                break
        if not ts_text:
            ts_text = text[:5000]

        return ParsedLot(
            lot_id=lot_id,
            title=title,
            customer_name=customer_name or "Не указан",
            customer_bin=customer_bin,
            method=method,
            deadline=deadline,
            budget_kzt=budget_kzt,
            description=text[:3000],
            technical_specification=ts_text,
            raw_html=html,
            extra={"source_url": source_url},
        )


def _attach_source_url(parsed: ParsedLot, reference: GoszakupReference) -> None:
    """Сохраняет каноническую ссылку на объявление в extra лота.

    HTML-путь кладёт source_url сам, GraphQL — нет. Без этого ссылки
    «Открыть на Госзакупках» на странице анализа не появляются.
    Значение из extra не перетираем: парсер HTML знает URL фактического
    редиректа, он точнее.
    """
    if parsed.extra.get("source_url"):
        return
    if reference.source_url:
        parsed.extra["source_url"] = reference.source_url


def build_lot_url(lot_id_or_url: str | None) -> str | None:
    """Каноническая ссылка на goszakup по ID/ссылке либо None.

    Мягкая версия parse_reference: не бросает исключение на мусорном вводе,
    потому что используется в UI-слое (история, песочница), где ID может
    оказаться чем угодно.
    """
    if not lot_id_or_url:
        return None
    try:
        reference = GoszakupParser.parse_reference(str(lot_id_or_url))
    except ValueError:
        return None
    return reference.source_url


_parser: GoszakupParser | None = None


def get_parser() -> GoszakupParser:
    global _parser
    if _parser is None:
        _parser = GoszakupParser()
    return _parser


async def close_parser() -> None:
    global _parser
    if _parser is not None:
        await _parser.close()
    _parser = None

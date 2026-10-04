"""Извлечение структурированных данных о товарах из HTML страницы.

Зачем нужен этот модуль
-----------------------
Раньше агент поиска поставщиков получал страницу через Jina Reader (markdown-текст)
и искал цены регулярными выражениями по тексту. Это ненадёжно по двум причинам:

1. Вёрстка магазина меняется — селекторы/классы «плывут».
2. Рядом с числом может не быть слова «тг»/«₸»/«тенге», поэтому regex по тексту
   молча возвращает 0 совпадений (проверено на ankas.kz: 755 КБ HTML, 0 совпадений
   по ``[0-9][0-9 ]{2,}\\s*(тг|₸|тенге)``).

Цены у этих сайтов лежат в HTML как микроразметка schema.org:

    <meta itemprop="price" content="33000" />
    <meta itemprop="priceCurrency" content="KZT" />

Поэтому мы разбираем HTML напрямую, а не текст.

Приоритет источников (по убыванию): JSON-LD → microdata → OpenGraph → таблицы.
Записи дедуплицируются по паре (имя, цена) с приоритетом источника и сортируются
в порядке следования в HTML: на каталоге товары идут в порядке выдачи, и приписывать
«первую цену со страницы» нельзя — это была старография (см. ``pick_price``).

Модуль чистый: сетевых вызовов нет, на вход HTML-строка, на выход dataclass'ы.
Любая ошибка внутри гасится и даёт пустой/частичный результат, но НИКОГДА
не выпускает исключение наружу — иначе один битый сайт роняет поиск поставщиков.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Final

try:  # lxml — основной парсер: быстрый, даёт sourceline (порядок в документе)
    from lxml import etree
    from lxml import html as lxml_html

    _HAS_LXML: Final[bool] = True
except ImportError:  # pragma: no cover - деградация, см. _extract_via_regex
    _HAS_LXML: Final[bool] = False

__all__ = ["ProductRecord", "extract_products", "normalize_price", "pick_price"]


# ---------------------------------------------------------------------------
# Лимиты: нужны, чтобы 2 МБ чужого HTML не положили процесс по времени/памяти
# ---------------------------------------------------------------------------
_MAX_HTML_CHARS: Final[int] = 8_000_000
_MAX_RECORDS: Final[int] = 2_000
_MAX_JSON_DEPTH: Final[int] = 25
_MAX_JSON_NODES: Final[int] = 20_000
_MAX_NAME_CHARS: Final[int] = 300


# ---------------------------------------------------------------------------
# Валюты
# ---------------------------------------------------------------------------
# Порядок важен: USD проверяется раньше KZT, потому что "$" и "₸" не пересекаются,
# но "тг" внутри "тенге" требует более длинной альтернативы.
_CURRENCY_MARKERS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("USD", ("usd", "$", "доллар", "долларов", "долл")),
    ("EUR", ("eur", "€", "евро")),
    ("RUB", ("rub", "₽", "руб", "рублей")),
    ("KZT", ("kzt", "₸", "тг", "тңг", "тенге", "тэнгэ")),
)

_NON_KZT_CURRENCIES: Final[frozenset[str]] = frozenset({"USD", "EUR", "RUB"})


def _detect_currency(raw: str) -> tuple[str | None, bool]:
    """Определить валюту в строке.

    Возвращает ``(код_валюты, найдена_ли_не_тенге)``. Вторая часть ответа нужна,
    чтобы отличать «явно указана чужая валюта» (значит, это НЕ тенге и price_kzt
    обязан быть None) от «валюты не указано» (тогда считаем KZT по умолчанию).
    """
    low = raw.lower()
    foreign = False
    kzt = False
    for code, markers in _CURRENCY_MARKERS:
        if code == "KZT":
            kzt = any(m in low for m in markers)
            continue
        if any(m in low for m in markers):
            foreign = True
    if foreign:
        return None, True
    return ("KZT" if kzt else None), False


# Пробелы-разделители тысяч: обычный, неразрывный, узкий неразрывный, thin space.
# Храним БЕЗ квадратных скобок — набор подставляется внутрь [ ] в регулярках.
_SPACE_CLASS: Final[str] = r" \u00a0\u202f\u2009"
_SPACE_RE: Final[re.Pattern[str]] = re.compile(r"[" + _SPACE_CLASS + r"'\u2019]")
_NUM_RE: Final[re.Pattern[str]] = re.compile(r"\d[\d" + _SPACE_CLASS + r".,'\u2019]*")


def normalize_price(raw: str | None) -> float | None:
    """Разобрать строку цены в число тенге.

    Понимает: «107000», «107 000», «107 000,00», «₸107 000», «107,000.00»,
    «KZT 107000», «19 994».

    Возвращает ``None``, если в строке мусор, нет чисел, либо явно указана
    НЕ тенге (USD/$/EUR/€/RUB) — чужая валюта не выдаётся за тенге, потому что
    это прямое искажение цены для тенгового расчёта.

    Оговорка про неоднозначность: «107.000» трактуется как 107 000 (казахская/русская
    запись тысяч), а «107.5» — как 107,5. Решение берётся по длине хвоста после
    последнего разделителя: 1–2 цифры → десятичный, 3+ → тысячи.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # «Цена по запросу» / «уточнить цену» — это отсутствие цены, а не ноль.
    low = text.lower()
    if "по запросу" in low or "уточнить цену" in low or "цена не указана" in low:
        return None

    _, is_foreign = _detect_currency(text)
    if is_foreign:
        return None

    match = _NUM_RE.search(text)
    if not match:
        return None

    # Убираем разделители тысяч: пробелы всех сортов, апострофы, неразрывные пробелы
    num = _SPACE_RE.sub("", match.group())
    if not num or num.count(",") + num.count(".") > 6:  # явно мусор, не цена
        return None

    try:
        value = _parse_number_with_separators(num)
    except (TypeError, ValueError):
        return None
    return value


def _parse_number_with_separators(num: str) -> float | None:
    """Разобрать число, где запятая/точка могут быть и разделителем тысяч, и знаком."""
    has_comma = "," in num
    has_dot = "." in num

    if has_comma and has_dot:
        # Десятичным считаем ТОТ разделитель, который стоит правее: «107,000.00»
        decimal_sep = "," if num.rfind(",") > num.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        num = num.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in num:
        head, _, tail = num.rpartition(",")
        # Хвост из 1–2 цифр → десятичная запятая («107000,50»); иначе разделитель тысяч
        if len(tail) in (1, 2) and head:
            num = f"{head}.{tail}"
        else:
            num = num.replace(",", "")
    elif has_dot:
        parts = num.split(".")
        tails = [p for p in parts[1:]]
        if tails and all(len(t) in (1, 2) for t in tails):
            num = ".".join(parts)  # «19.5»
        else:
            num = "".join(parts)  # «107.000» → 107000

    if not num or not re.fullmatch(r"\d*\.?\d*", num):
        return None
    value = float(num)
    return value if math.isfinite(value) else None


# ---------------------------------------------------------------------------
# Модель
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ProductRecord:
    """Один товар, извлечённый из страницы.

    ``price_kzt`` — только число в тенге. Если цены на странице нет, это ``None``:
    выдумывать цену нельзя, отсутствие цены — это факт, а не ошибка.
    ``raw_price`` сохранён для отладки и для ручной сверки с исходной страницей.
    """

    name: str
    price_kzt: float | None
    currency: str | None
    in_stock: bool | None
    source: str
    raw_price: str


# ---------------------------------------------------------------------------
# Текстовые утилиты
# ---------------------------------------------------------------------------
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_PLACEHOLDER_NAMES: Final[frozenset[str]] = frozenset(
    {"-", "--", "—", "n/a", "na", "нет", "нет данных", "0", "null", "none"}
)


def _clean_name(raw: str | None) -> str:
    """Схлопнуть пробелы, обрезать по длине, отбросить служебные заглушки."""
    if not raw:
        return ""
    name = _WS_RE.sub(" ", str(raw).replace("\xa0", " ")).strip()
    if len(name) > _MAX_NAME_CHARS:
        name = name[:_MAX_NAME_CHARS].rstrip()
    return "" if name.lower() in _PLACEHOLDER_NAMES else name


def _prop_tokens(node: Any, attr: str) -> list[str]:
    """Разбить itemprop/itemtype на токены (они могут быть списком через пробел)."""
    raw = node.get(attr)
    return [t.lower() for t in raw.split()] if raw else []


def _prop_value(node: Any) -> str:
    """Значение свойства: сначала content/href (элементы <meta>/<link>), потом текст."""
    for attr in ("content", "href", "datetime", "value", "src"):
        val = node.get(attr)
        if val:
            return str(val).strip()
    return _WS_RE.sub(" ", node.text_content() or "").strip()


def _parse_availability(raw: str | None) -> bool | None:
    """«InStock» → True, «OutOfStock»/«Discontinued» → False, неизвестно → None."""
    if not raw:
        return None
    low = raw.lower().replace("_", "").replace("-", "").replace(" ", "")
    if any(k in low for k in ("instock", "limitedavailability", "onlineonly", "preorder")):
        return True
    if any(k in low for k in ("outofstock", "soldout", "discontinued", "unavailable")):
        return False
    return None


def _positive(price: float | None) -> float | None:
    """Ноль на карточках ankas — это заглушка «Уточнить цену», а не бесплатный товар."""
    return price if price is not None and price > 0 else None


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def extract_products(html: str | None) -> list[ProductRecord]:
    """Извлечь все товары с ценами из HTML.

    Возвращает записи в порядке следования в документе. Любая ошибка внутри
    гасится: результат может оказаться пустым, но исключение не выйдет наружу.
    """
    if not html or not isinstance(html, str):
        return []
    if len(html) > _MAX_HTML_CHARS:
        html = html[:_MAX_HTML_CHARS]
    try:
        return _extract_all(html)
    except Exception:  # noqa: BLE001 - контракт модуля: не падать на битом HTML
        return []


def _extract_all(html: str) -> list[ProductRecord]:
    if not _HAS_LXML:
        return _extract_via_regex(html)

    try:
        doc = lxml_html.document_fromstring(html)
    except Exception:  # noqa: BLE001 - битая разметка
        try:
            doc = etree.fromstring(html.encode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            return _extract_via_regex(html)

    candidates: list[tuple[int, int, ProductRecord]] = []
    seq = 0

    def add(record: ProductRecord, order: int) -> None:
        nonlocal seq
        if len(candidates) >= _MAX_RECORDS:
            return
        candidates.append((order, seq, record))
        seq += 1

    # Приоритет источников: сначала JSON-LD (самая надёжная микроразметка),
    # затем microdata, потом OpenGraph, и только потом таблицы.
    for order, record in _iter_json_ld(doc):
        add(record, order)
    for order, record in _iter_microdata(doc):
        add(record, order)
    for order, record in _iter_opengraph(doc):
        add(record, order)
    for order, record in _iter_tables(doc):
        add(record, order)

    candidates.sort(key=lambda item: (item[0], item[1]))
    return _dedupe([record for _, _, record in candidates])


def _dedupe(records: list[ProductRecord]) -> list[ProductRecord]:
    """Убрать точные дубли (имя+цена), сохранив первое вхождение и приоритет источника."""
    priority = {"json_ld": 0, "microdata": 1, "opengraph": 2, "table": 3}
    best: dict[tuple[str, float | None], tuple[int, ProductRecord]] = {}
    result: list[ProductRecord] = []
    for index, record in enumerate(records):
        key = (_norm_key(record.name), record.price_kzt)
        current = best.get(key)
        if current is None:
            best[key] = (index, record)
            result.append(record)
            continue
        # Та же цена и то же имя из более приоритетного источника — заменяем.
        if priority.get(record.source, 9) < priority.get(current[1].source, 9):
            result[current[0]] = record
            best[key] = (current[0], record)
    return result


# ---------------------------------------------------------------------------
# Источник 1: schema.org JSON-LD
# ---------------------------------------------------------------------------
def _iter_json_ld(doc: Any) -> list[tuple[int, ProductRecord]]:
    """Разобрать <script type="application/ld+json">.

    Учитываем ``@graph``, ``offers`` (в т.ч. список), ``AggregateOffer``
    (``lowPrice``/``highPrice``) и ``priceSpecification``. Рекурсия ограничена
    по глубине и числу узлов: битый/циклический JSON не должен вешать процесс.
    """
    out: list[tuple[int, ProductRecord]] = []
    budget = _MAX_JSON_NODES

    for script in doc.iter("script"):
        if (script.get("type") or "").strip().lower() != "application/ld+json":
            continue
        raw = script.text or script.text_content() or ""
        data = _loads_lenient(raw)
        if data is None:
            continue
        base = _line_of(script) * 1000
        for offset, record in _walk_jsonld(data, budget=budget):
            out.append((base + offset, record))
            budget -= 1
            if budget <= 0:
                return out
    return out


def _loads_lenient(raw: str) -> Any | None:
    """json.loads с мягким восстановлением: сайты часто ломают разметку.

    Типовые поломки: HTML-комментарии внутри JSON, висячие запятые, BOM,
    переименованный в ``application/LD+JSON`` тип. Любой сбой → None, не исключение.
    """
    text = raw.strip()
    if not text:
        return None
    text = text.removeprefix("﻿")
    for attempt in (text, _strip_comments(text), _drop_trailing_commas(_strip_comments(text))):
        try:
            return json.loads(attempt)
        except (ValueError, TypeError):
            continue
    return None


def _strip_comments(text: str) -> str:
    without = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"(^|\s)//[^\n\"']*", r"\1", without)


def _drop_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _type_names(node: Any) -> set[str]:
    """Множество типов schema.org узла (``@type`` может быть строкой или списком)."""
    if not isinstance(node, dict):
        return set()
    raw = node.get("@type") or node.get("type")
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = [v for v in raw if isinstance(v, str)]
    else:
        return set()
    return {v.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1].lower() for v in values}


def _walk_jsonld(
    node: Any,
    *,
    budget: int = _MAX_JSON_NODES,
    depth: int = 0,
    counter: list[int] | None = None,
) -> list[tuple[int, ProductRecord]]:
    """Обойти JSON-LD и выдать записи для каждого Product.

    Возвращает пары (порядковый номер внутри скрипта, запись).
    """
    if counter is None:
        counter = [0]
    out: list[tuple[int, ProductRecord]] = []

    def walk(current: Any, level: int) -> None:
        if level > _MAX_JSON_DEPTH or counter[0] >= budget:
            return
        if isinstance(current, dict):
            counter[0] += 1
            types = _type_names(current)
            record = _product_from_node(current, types)
            if record is not None:
                out.append((counter[0], record))
                return
            for value in current.values():
                if isinstance(value, (dict, list)):
                    walk(value, level + 1)
        elif isinstance(current, list):
            counter[0] += 1
            for item in current:
                if isinstance(item, (dict, list)):
                    walk(item, level + 1)

    walk(node, depth)
    return out


def _is_foreign_currency(currency: Any) -> bool:
    """Явно заданная не-тенге валюта (priceCurrency / og:price:currency)."""
    if not currency:
        return False
    return any(
        marker in str(currency).lower()
        for marker in ("usd", "eur", "rub", "gbp", "jpy", "cny", "uah", "$", "€", "₽", "£")
    )


def _product_from_node(node: dict[str, Any], types: set[str]) -> ProductRecord | None:
    """Собрать запись из узла, если это Product/ProductGroup с ценой."""
    if not (types & {"product", "productgroup", "individualproduct"}):
        return None

    name = _clean_name(node.get("name") or node.get("title"))
    raw_price, currency, availability = _price_from_offers(node.get("offers"))
    if raw_price is None:
        # Некоторые магазины кладут цену прямо в Product, без offers
        raw_price = node.get("price")
        currency = currency or node.get("priceCurrency")
        availability = availability or node.get("availability")

    price = _positive(normalize_price(str(raw_price) if raw_price is not None else None))
    if price is None and not name:
        return None
    if price is None and name and not raw_price:
        return None
    # Валюта в JSON-LD лежит отдельным полем priceCurrency, а не в строке цены,
    # поэтому normalize_price её не видит — проверяем явно.
    if price is not None and _is_foreign_currency(currency):
        return None
    return ProductRecord(
        name=name,
        price_kzt=price,
        currency=(currency or "KZT") if price is not None else currency,
        in_stock=_parse_availability(availability),
        source="json_ld",
        raw_price=str(raw_price) if raw_price is not None else "",
    )


def _price_from_offers(offers: Any) -> tuple[Any, str | None, str | None]:
    """Достать (сырая цена, валюта, наличие) из offers любой вложенности.

    Для ``AggregateOffer`` берём ``lowPrice`` (цена «от»), потому что именно её
    показывают как актуальную; ``highPrice`` — верхняя граница диапазона, приписывать
    её как цену товара нельзя.
    """
    stack: list[Any] = [offers]
    seen = 0
    while stack and seen < 200:
        seen += 1
        current = stack.pop(0)
        if isinstance(current, list):
            stack.extend(current)
            continue
        if not isinstance(current, dict):
            continue
        raw = current.get("price") or current.get("lowPrice")
        if raw is None:
            specs = current.get("priceSpecification")
            if isinstance(specs, dict):
                raw = specs.get("price") or specs.get("minPrice")
            elif isinstance(specs, list):
                for spec in specs:
                    if isinstance(spec, dict) and spec.get("price") is not None:
                        raw = spec["price"]
                        break
        if raw is not None:
            currency = current.get("priceCurrency")
            if isinstance(currency, dict):
                currency = currency.get("name") or currency.get("symbol")
            if isinstance(currency, list) and currency:
                currency = currency[0]
            return raw, (str(currency) if currency else None), current.get("availability")
        stack.extend(v for v in current.values() if isinstance(v, (dict, list)))
    return None, None, None


# ---------------------------------------------------------------------------
# Источник 2: schema.org microdata (именно так отдаёт ankas.kz)
# ---------------------------------------------------------------------------
def _iter_microdata(doc: Any) -> list[tuple[int, ProductRecord]]:
    """Разобрать microdata: ``itemprop="price"`` + ближайший ``itemprop="name"``.

    Идём по scope'ам (Product/Offer), а не по отдельным ``itemprop="price"``:
    на одной карточке цена может дублироваться (мобильная и десктопная вёрстка —
    так на pnevmoteh.kz), и обход по узлам дал бы дубли.
    """
    out: list[tuple[int, ProductRecord]] = []

    # Проход 1: карточки, помеченные как Product.
    # ВАЖНО: не используем id()/set для отметок — lxml создаёт временные прокси-объекты,
    # их идентификаторы переиспользуются, и отметки «уже обработан» попадали бы
    # на чужие элементы (проявлялось как нестабильное число товаров: то 3, то 8).
    for scope in doc.iter():
        if "itemscope" not in scope.attrib or not _is_product_scope(scope):
            continue
        types = _prop_tokens(scope, "itemtype")
        if not any("product" in t for t in types):
            continue
        # Товар внутри другого товара — карточка уже разобрана родителем.
        if _product_scope_ancestor(scope) is not None:
            continue
        record = _record_from_scope(scope)
        if record is not None:
            out.append((_line_of(scope) * 1000, record))

    # Проход 2: цены без Product-scope. Часть простых витрин размечает Offer или
    # вообще одиночные meta без товарного контейнера.
    for node in doc.iter():
        if "itemprop" not in node.attrib:
            continue
        if "price" not in _prop_tokens(node, "itemprop"):
            continue
        # Цена внутри Product-scope уже учтена в проходе 1.
        nearest = _nearest_scope(node)
        if nearest is not None and any(
            "product" in t for t in _prop_tokens(nearest, "itemtype")
        ):
            continue
        record = _record_from_loose_price(node)
        if record is not None:
            out.append((_line_of(node) * 1000, record))
    return out


def _product_scope_ancestor(node: Any) -> Any | None:
    """Ближайший scope типа Product ABOVE узла (вложенный Offer его не считаем)."""
    parent = node.getparent()
    current = _nearest_scope(parent) if parent is not None else None
    while current is not None:
        if any("product" in t for t in _prop_tokens(current, "itemtype")):
            return current
        up = current.getparent()
        current = _nearest_scope(up) if up is not None else None
    return None


def _product_scope_ancestor(node: Any) -> Any | None:
    """Ближайший scope типа Product ABOVE узла (вложенный Offer его не считаем)."""
    current = _nearest_scope(node.getparent()) if node.getparent() is not None else None
    while current is not None:
        if any("product" in t for t in _prop_tokens(current, "itemtype")):
            return current
        parent = current.getparent()
        current = _nearest_scope(parent) if parent is not None else None
    return None


def _is_product_scope(node: Any) -> bool:
    """Scope типа Product/Offer/AggregateOffer (а не Brand, BreadcrumbList и т.п.)."""
    types = _prop_tokens(node, "itemtype")
    if not types:
        return False
    return any(
        t.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        in {"product", "productgroup", "offer", "aggregateoffer"}
        for t in types
    )


def _nearest_scope(node: Any) -> Any | None:
    current = node
    while current is not None:
        if "itemscope" in current.attrib:
            return current
        parent = current.getparent()
        if parent is None:
            return None
        current = parent
    return None


def _record_from_scope(scope: Any) -> ProductRecord | None:
    name = _pick_name(scope)
    currency = _scope_currency(scope)
    # Чужая валюта (RUB/USD/EUR) — это не «цена в тенге». На живых данных
    # pnm-parts.ru отдаёт priceCurrency="RUB" с ценой 492.88, и без этой
    # проверки рубли выдавались поставщику как тенги.
    if _is_foreign_currency(currency):
        return None
    price_nodes = [n for n in scope.iter() if "price" in _prop_tokens(n, "itemprop")]
    price_nodes = _own_props(price_nodes, scope)
    raw = _prop_value(price_nodes[0]) if price_nodes else ""
    price = _positive(normalize_price(raw))
    # Карточка без названия и без цены бесполезна; с ценой-но-без-имени — нет.
    if not name and price is None:
        return None
    return ProductRecord(
        name=name,
        price_kzt=price,
        currency=currency,
        in_stock=_scope_availability(scope),
        source="microdata",
        raw_price=raw,
    )


def _record_from_loose_price(node: Any) -> ProductRecord | None:
    """Цена без Product-scope: имя ищем в ближайшем контейнере с itemprop=name."""
    raw = _prop_value(node)
    name = ""
    container = node.getparent()
    hops = 0
    while container is not None and hops < 4:
        names = [
            n
            for n in container.iter()
            if any(t in {"name", "title"} for t in _prop_tokens(n, "itemprop"))
        ]
        for candidate in _own_props(names, container) or names:
            cleaned = _clean_name(_prop_value(candidate))
            if cleaned:
                name = cleaned
                break
        if name:
            break
        container = container.getparent()
        hops += 1
    return ProductRecord(
        name=name,
        price_kzt=_positive(normalize_price(raw)),
        currency=None,
        in_stock=None,
        source="microdata",
        raw_price=raw,
    )


def _own_props(nodes: list[Any], scope: Any, block: Any | None = None) -> list[Any]:
    """Оставить только свойства, принадлежащие этому scope, а не вложенным.

    Вложенный Offer ПРИНАДЛЕЖИТ товару (там по spec.org и живёт цена), поэтому его
    пропускать нельзя — блокируем только вложенные scope'ы, для которых
    ``block`` возвращает True. По умолчанию это вложенный Product: цена соседнего
    товара не должна приписываться текущему.
    """
    block = block or _is_nested_product

    def is_blocked(candidate: Any) -> bool:
        current = candidate
        while current is not None and current is not scope:
            parent = current.getparent()
            if parent is None:
                return False
            if "itemscope" in parent.attrib and parent is not scope and block(parent):
                return True
            current = parent
        return False

    return [node for node in nodes if not is_blocked(node)]


def _is_nested_product(scope: Any) -> bool:
    """Вложенный scope типа Product (другой товар в том же блоке)."""
    return any("product" in t for t in _prop_tokens(scope, "itemtype"))


def _pick_name(scope: Any) -> str:
    """Название товара: первое осмысленное имя, не принадлежащее Brand-вложенности."""
    names = [
        n
        for n in scope.iter()
        if any(t in {"name", "title"} for t in _prop_tokens(n, "itemprop"))
    ]
    candidates = _own_props(names, scope)
    cleaned: list[str] = []
    for node in candidates or names:
        if _is_inside_brand(node, scope):
            continue
        value = _clean_name(_prop_value(node))
        if value:
            cleaned.append(value)
    if cleaned:
        # Берём самое длинное осмысленное: рядом обычно лежит короткий бренд,
        # а полное название товара — длиннее.
        return max(cleaned, key=len)
    for node in candidates or names:
        value = _clean_name(_prop_value(node))
        if value:
            return value
    return ""


def _is_inside_brand(node: Any, scope: Any) -> bool:
    """Находится ли свойство внутри Brand/Organization (т.е. это бренд, а не товар)?"""
    current = node
    while current is not None and current is not scope:
        parent = current.getparent()
        if parent is None:
            return False
        types = _prop_tokens(parent, "itemtype")
        if any(t.rstrip("/").rsplit("/", 1)[-1] in {"brand", "organization"} for t in types):
            return True
        if "brand" in _prop_tokens(parent, "itemprop"):
            return True
        current = parent
    return False


def _scope_currency(scope: Any) -> str | None:
    for node in scope.iter():
        if "pricecurrency" in _prop_tokens(node, "itemprop"):
            return _prop_value(node) or None
    return None


def _scope_availability(scope: Any) -> bool | None:
    for node in scope.iter():
        if "availability" in _prop_tokens(node, "itemprop"):
            parsed = _parse_availability(_prop_value(node))
            if parsed is not None:
                return parsed
    return None


# ---------------------------------------------------------------------------
# Источник 3: OpenGraph / product-meta
# ---------------------------------------------------------------------------
def _iter_opengraph(doc: Any) -> list[tuple[int, ProductRecord]]:
    """``og:price:amount`` / ``product:price:amount`` + валюта и название.

    Применимо в основном к странице одного товара (у карточки товара есть og-теги).
    """
    fields: dict[str, str] = {}
    order = 0
    for node in doc.iter("meta"):
        key = node.get("property") or node.get("name")
        if not key:
            continue
        key = key.strip().lower()
        content = (node.get("content") or "").strip()
        if content and key not in fields:
            fields[key] = content
            order = max(order, _line_of(node))

    raw = (
        fields.get("product:price:amount")
        or fields.get("og:price:amount")
        or fields.get("og:price")
        or fields.get("product:sale_price:amount")
    )
    if not raw:
        return []
    price = _positive(normalize_price(raw))
    if price is None:
        return []

    currency = (
        fields.get("product:price:currency")
        or fields.get("og:price:currency")
        or fields.get("og:price:standard_amount_currency")
        or fields.get("product:price:standard_amount_currency")
    )
    # Валюта может быть задана отдельным тегом: normalize_price смотрит только на
    # строку цены. Без этой проверки «og:price:amount=49.99» + «currency=USD»
    # превратился бы в 49.99 тенге.
    if _is_foreign_currency(currency):
        return []
    name = fields.get("product:name") or fields.get("og:title") or fields.get("twitter:title")
    availability = _parse_availability(
        fields.get("product:availability") or fields.get("og:availability")
    )
    return [
        (
            order,
            ProductRecord(
                name=_clean_name(name),
                price_kzt=price,
                currency=currency,
                in_stock=availability,
                source="opengraph",
                raw_price=raw,
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Источник 4: обычные HTML-таблицы (страницы-прайсы)
# ---------------------------------------------------------------------------
_PRICE_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"цена|стоимость|price|сумма", re.IGNORECASE
)
_NAME_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"наименование|название|товар|продукт|артикул|код|модель|name|product", re.IGNORECASE
)


def _iter_tables(doc: Any) -> list[tuple[int, ProductRecord]]:
    """Строки таблиц, где в одной ячейке число, а в соседней — название/«цена»."""
    out: list[tuple[int, ProductRecord]] = []
    for table in doc.iter("table"):
        rows = [r for r in table.iter("tr")]
        if not rows:
            continue
        header_price_idx = _detect_price_column(rows[0])
        for offset, row in enumerate(rows if header_price_idx is None else rows[1:], start=1):
            cells = [c for c in row.iter("td", "th")]
            if len(cells) < 2:
                continue
            texts = [_WS_RE.sub(" ", c.text_content()).strip() for c in cells]
            price_idx = header_price_idx if header_price_idx is not None else _guess_price_cell(texts)
            if price_idx is None or not (0 <= price_idx < len(texts)):
                continue
            raw = texts[price_idx]
            price = _positive(normalize_price(raw))
            if price is None:
                continue
            name = _row_name(texts, price_idx)
            if not name:
                continue
            out.append(
                (
                    _line_of(row) * 1000 + offset,
                    ProductRecord(
                        name=_clean_name(name),
                        price_kzt=price,
                        currency=None,
                        in_stock=None,
                        source="table",
                        raw_price=raw,
                    ),
                )
            )
    return out


def _detect_price_column(header_row: Any) -> int | None:
    """Найти колонку «Цена» по шапке таблицы, если шапка распознана."""
    texts = [_WS_RE.sub(" ", c.text_content()).strip() for c in header_row.iter("td", "th")]
    if not texts or not any(_PRICE_HEADER_RE.search(t) for t in texts):
        return None
    if any(_NAME_HEADER_RE.search(t) for t in texts):
        for index, text in enumerate(texts):
            if _PRICE_HEADER_RE.search(text):
                return index
    return None


def _guess_price_cell(texts: list[str]) -> int | None:
    """Без шапки: цена — единственная ячейка, которая целиком парсится в число."""
    hits = [i for i, t in enumerate(texts) if normalize_price(t) is not None and t.strip()]
    if len(hits) != 1:
        return None
    return hits[0]


def _row_name(texts: list[str], price_idx: int) -> str:
    """Название в соседней ячейке: сперва слева (обычная прайс-таблица), затем справа."""
    for candidate in (price_idx - 1, price_idx + 1):
        if 0 <= candidate < len(texts):
            text = texts[candidate]
            if text and not _PRICE_HEADER_RE.fullmatch(text):
                return text
    return ""


# ---------------------------------------------------------------------------
# Порядок в документе
# ---------------------------------------------------------------------------
def _line_of(node: Any) -> int:
    line = getattr(node, "sourceline", None)
    return line if isinstance(line, int) and line > 0 else 0


# ---------------------------------------------------------------------------
# Выбор цены по названию товара
# ---------------------------------------------------------------------------
def _norm_key(text: str) -> str:
    """Нормализовать название для сравнения: регистр, «ё»/«е», пунктуация."""
    low = (text or "").lower().replace("ё", "е").replace("\xa0", " ")
    return _WS_RE.sub(" ", re.sub(r"[^\w\s]", " ", low, flags=re.UNICODE)).strip()


def _norm_words(text: str) -> list[str]:
    return [w for w in _norm_key(text).split() if w]


def pick_price(products: list[ProductRecord], term: str) -> float | None:
    """Выбрать цену товара, название которого содержит ``term``.

    Сравнение регистронезависимое и по нормализованным словам: «Фильтр для ТОПЛИВА»
    найдётся по термину «фильтр топлива», знаки препинания не важны.

    Возвращается цена ПЕРВОГО совпадения в порядке HTML. Это принципиально: на
    каталоге товары идут в порядке выдачи, а «взять первую цену со страницы» —
    классическая ошибка, из-за которой агенту приписывался чужой товар.

    Нюанс: если первое совпадение не имеет цены (например, «Цена по запросу»),
    берётся цена следующего совпадения — так мы отдаём что-то проверенное, а не
    пустоту. Если цен нет ни у одного совпадения — возвращается ``None``.
    """
    if not products or not term or not str(term).strip():
        return None
    term_words = _norm_words(str(term))
    if not term_words:
        return None

    for record in products:
        name_words = _norm_words(record.name)
        if not name_words:
            continue
        if not all(word in name_words for word in term_words):
            continue
        # Вторая линия защиты: цена в чужой валюте не является ценой в тенге.
        if _is_foreign_currency(record.currency):
            continue
        if record.price_kzt is not None and record.price_kzt > 0:
            return record.price_kzt
    return None


# ---------------------------------------------------------------------------
# Деградация без lxml
# ---------------------------------------------------------------------------
_SCRIPT_LD_RE: Final[re.Pattern[str]] = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_META_RE: Final[re.Pattern[str]] = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR_RE: Final[re.Pattern[str]] = re.compile(
    r"""(\w[\w:-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.IGNORECASE
)


def _parse_tag(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(tag):
        name = match.group(1).lower()
        value = match.group(2) or match.group(3) or match.group(4) or ""
        attrs[name] = value
    return attrs


def _extract_via_regex(html: str) -> list[ProductRecord]:
    """Запасной путь на регулярках, если lxml не установлен.

    Покрывает JSON-LD и OpenGraph (они плоские). Microdata и таблицы требуют
    обхода дерева, поэтому здесь они не разбираются — честная деградация.
    """
    records: list[tuple[int, int, ProductRecord]] = []
    for index, match in enumerate(_SCRIPT_LD_RE.finditer(html)):
        data = _loads_lenient(match.group(1))
        if data is None:
            continue
        for offset, record in _walk_jsonld(data):
            records.append((index, offset, record))

    fields: dict[str, str] = {}
    order = 0
    for index, match in enumerate(_META_RE.finditer(html)):
        attrs = _parse_tag(match.group(0))
        key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
        content = attrs.get("content", "").strip()
        if content and key and key not in fields:
            fields[key] = content
            order = index
    raw = (
        fields.get("product:price:amount")
        or fields.get("og:price:amount")
        or fields.get("og:price")
    )
    currency = fields.get("product:price:currency") or fields.get("og:price:currency")
    price = _positive(normalize_price(raw)) if raw else None
    if price is not None and _is_foreign_currency(currency):
        price = None
    if price is not None:
        records.append(
            (
                order,
                0,
                ProductRecord(
                    name=_clean_name(
                        fields.get("product:name")
                        or fields.get("og:title")
                        or fields.get("twitter:title")
                    ),
                    price_kzt=price,
                    currency=currency,
                    in_stock=_parse_availability(
                        fields.get("product:availability") or fields.get("og:availability")
                    ),
                    source="opengraph",
                    raw_price=raw or "",
                ),
            )
        )

    records.sort(key=lambda item: (item[0], item[1]))
    return _dedupe([record for _, _, record in records])
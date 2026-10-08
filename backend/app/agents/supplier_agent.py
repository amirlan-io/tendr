"""SupplierAgent: поиск поставщиков по требованиям лота и сверка по пунктам ТЗ (F1–F2).

Конвейер:
    требования Documenter → 3–7 поисковых запросов (LLM) → Tavily
    → для топ-кандидатов: Browser-Use читает страницу поставщика
    → LLM сверяет каждый пункт ТЗ → статусы + score + предупреждения

Важные инварианты:
* агент только ИЩЕТ — ни одного исходящего контакта;
* каждый статус по пункту ТЗ ссылается на источник (`source_url`), иначе
  статус `unknown` — «нет данных» честнее, чем выдумка;
* стоп-лист поставщика фильтруется ДО показа (F6/F7);
* стоимость каждого шага пишется в аудит (F10).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from app.agents.base import Agent
from app.core.config import get_settings

# Маркетплейсы и доски объявлений: быстрый путь, но там почти всегда
# посредник и спрятанные за кнопкой контакты.
DEFAULT_SEARCH_DOMAINS: tuple[str, ...] = (
    "kaspi.kz",
    "sulpak.kz",
    "technodom.kz",
    "olx.kz",
    "shop.kz",
    "mechta.kz",
    "bifi.kz",
    "marwin.kz",
    "vernal.kz",
    "satbay.kz",
    "m.kz",
    "flagma.kz",
)

# Второй проход: ищем САМОГО производителя/дистрибьютора, без ограничения
# доменов. На сайтах компаний контакты почти всегда есть открытым текстом,
# а цена ниже, потому что нет наценки площадки.
DIRECT_QUERY_HINTS: tuple[str, ...] = (
    "производитель",
    "оптом",
    "завод",
    "поставщик",
    "дистрибьютор",
    "оптовая продажа",
    "производство",
)

#: Уценка маржа за посредничество: прямой поставщик приоритетнее.
DIRECT_SUPPLIER_BONUS = 12

# Признаки посредника: страница не производителя, а маркетплейса/доски объявлений.
MIDDLEMAN_DOMAINS = {"kaspi.kz", "olx.kz", "sulpak.kz", "technodom.kz", "avito.kz"}

#: Агрегаторы и маркетплейсы. Наличие товара там не означает, что продаёт
#: производитель — цена выше и контактов Often нет.
AGGREGATOR_DOMAINS = {
    "kaspi.kz", "olx.kz", "sulpak.kz", "technodom.kz", "flagma.kz", "satu.kz",
    "pulscen.kz", "prom.ua", "avito.kz", "prom.kz", "blizko.kz", "vsevoli.kz",
    "shopping.kz", "mag.kz", "market.kz", "tavito.kz", "obyavlenie.kz",
    "prom24.kz", "deal.by", "ucoz.kz",
}

#: Доски объявлений и соцсети — там контактов продавца обычно нет.
CLASSIFIEDS_DOMAINS = {
    "facebook.com", "instagram.com", "vk.com", "t.me", "telegram.me",
    "youtube.com", "linkedin.com", "ok.ru", "pinterest.com",
}

#: Признаки прямого производителя/дилера на странице.
_DIRECT_HINTS = (
    "производство", "производитель", "завод", "фабрика", "собственное производство",
    "дилер", "официальный дилер", "оптом", "оптовые цены", "оптовый отдел",
    "контакты", "наши контакты", "о нас", "контактная информация",
)

#: Суффиксы, которые направляют Tavily к сайтам компаний, а не к витринам.
_MANUFACTURER_QUERY_SUFFIXES = (
    "производитель казахстан",
    "оптом напрямую от производителя",
    "официальный сайт поставщика",
    "завод изготовитель казахстан",
    "дилерский центр",
)

# Email ищем аккуратно:
#  * (?<![0-9-]) — не начинатьmatch посреди номера телефона (было «312-26-99info@…»);
#  * домен верхнего уровня только из букв — иначе «.kz9» попадал в адрес.
_EMAIL_RE = re.compile(
    r"(?<![0-9\-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b"
)
# Основной формат: +7/8 с префиксом.
_PHONE_RE = re.compile(r"(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}")
# Казахстанский формат без префикса +7/8: 7 и ещё 10 цифр, между
# группами — дефисы (7801-31090-30). Дефисы обязательны: без них «7» и
# 10 случайных цифр дали бы много ложных срабатываний на страницах
# каталогов. Итоговое число цифр проверяется в find_contacts.
_PHONE_KZ_RE = re.compile(r"\b7[\d-]{11,17}\b")

#: Статусы сверки по пункту ТЗ (F2).
MATCH_FITS = "fits"
MATCH_PARTIAL = "partial"
MATCH_NO = "no"
MATCH_UNKNOWN = "unknown"

#: Сколько символов вокруг названия товара искать цену.
PRICE_WINDOW = 600

#: Цена с указанием валюты. «тенге» и «тң» обязательны: «тг» на реальных
#: сайтах встречается реже, из-за чего цены не читались вообще.
PRICE_RE = re.compile(r"([\d][\d\s]{1,11})\s*(?:₸|тг|тң|тенге|KZT)")

#: Начало строки с ценой/наличием — признак карточки товара, а не описания.
PRICE_MARKER_RE = re.compile(
    r"(?:цена|стоимость|цена\s+за|от\s+[\d\s]+(?:₸|тг|тң|тенге|KZT))",
    re.IGNORECASE,
)

VALID_MATCH_STATUSES = frozenset({MATCH_FITS, MATCH_PARTIAL, MATCH_NO, MATCH_UNKNOWN})


@dataclass(slots=True)
class Requirement:
    """Пункт ТЗ, по которому сверяем поставщика."""

    code: str
    title: str
    description: str = ""
    is_mandatory: bool = False


@dataclass(slots=True)
class Costs:
    """Оценка расходов и фактические счётчики вызовов.

    Провайдеры не возвращают подтверждённую сумму списания для каждого
    запроса. Поэтому денежные поля ниже — расчётная оценка, а не чек.
    Счётчики позволяют проверить, из чего эта оценка получилась.
    """

    llm_usd: float = 0.0
    tavily_usd: float = 0.0
    browser_usd: float = 0.0
    # Счётчики бесплатных операций — для отчётности по себестоимости.
    page_fetch_count: int = 0
    llm_calls: int = 0
    tavily_calls: int = 0
    tavily_attempts: int = 0
    browser_calls: int = 0

    def merge(self, other: Costs) -> None:
        self.llm_usd += other.llm_usd
        self.tavily_usd += other.tavily_usd
        self.browser_usd += other.browser_usd
        self.page_fetch_count += other.page_fetch_count
        self.llm_calls += other.llm_calls
        self.tavily_calls += other.tavily_calls
        self.tavily_attempts += other.tavily_attempts
        self.browser_calls += other.browser_calls


@dataclass(slots=True)
class SupplierCandidate:
    """Карточка поставщика с посимвольной сверкой."""

    supplier: str
    domain: str
    title: str
    url: str = ""
    price_kzt: float | None = None
    in_stock: bool | None = None
    city: str = ""
    delivery_days: int | None = None
    email: str = ""
    phone: str = ""
    image_url: str = ""
    certificates: list[str] = field(default_factory=list)
    warranty: str = ""
    sources: dict[str, str] = field(default_factory=dict)
    requirement_matches: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: int = 0
    is_middleman: bool = False
    # Тип площадки: direct (сайт компании) / aggregator (маркетплейс) /
    # classifieds (доска объявлений). Определяется classify_domain.
    domain_kind: str = "unknown"
    # Фрагмент реальной страницы/поисковой выдачи для доказательной сверки.
    # В API наружу не отдаётся целиком, чтобы не раздувать ответ.
    evidence_text: str = ""
    estimated_total_kzt: float | None = None
    budget_status: str = "unknown"  # within_budget / over_budget / unknown

    def to_card(self) -> dict[str, Any]:
        return {
            "name": self.title,
            "supplier": self.supplier,
            "domain": self.domain,
            "url": self.url,
            "price_kzt": self.price_kzt,
            "in_stock": self.in_stock,
            "city": self.city,
            "delivery_days": self.delivery_days,
            "email": self.email,
            "phone": self.phone,
            "image_url": self.image_url,
            "certificates": self.certificates,
            "warranty": self.warranty,
            "sources": self.sources,
            "is_middleman": self.is_middleman,
            "domain_kind": self.domain_kind,
            "estimated_total_kzt": self.estimated_total_kzt,
            "budget_status": self.budget_status,
        }

    def to_match(self) -> dict[str, Any]:
        return {
            "requirement_matches": self.requirement_matches,
            "score": self.score,
            "warnings": self.warnings,
        }


def extract_domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host.removeprefix("www.")


#: Национальные домены Казахстана. Поиск без ограничения доменов
#: неизбежно приносит российские и китайские площадки: перекрёстная
#: логистика, другая гарантия, часто нет документов для участия в
#: тендерах РК. Такие домены понижаем, казахстанские — поднимаем.
KZ_TLDS = (".kz", ".gov.kz", ".edu.kz", ".org.kz")
KZ_BONUS = 15
FOREIGN_PENALTY = 10


def domain_country_hint(domain: str) -> str:
    """kz / foreign / neutral — по суффиксу домена."""
    d = (domain or "").lower()
    if not d:
        return "neutral"
    if any(d.endswith(tld) for tld in KZ_TLDS):
        return "kz"
    if d.endswith((".ru", ".su", ".cn", ".by")):
        return "foreign"
    return "neutral"


def classify_domain(domain: str) -> str:
    """Классифицировать домен: direct / aggregator / classifieds / unknown.

    От этого зависит, покажем ли мы карточку как «прямого поставщика»
    и стоит ли с неё начинать поиск контактов.
    """
    d = (domain or "").lower()
    if not d:
        return "unknown"
    if any(d == s or d.endswith("." + s) for s in CLASSIFIEDS_DOMAINS):
        return "classifieds"
    if any(d == s or d.endswith("." + s) for s in AGGREGATOR_DOMAINS):
        return "aggregator"
    if d in DEFAULT_SEARCH_DOMAINS:
        return "aggregator"
    return "direct"


def looks_like_manufacturer(text: str) -> bool:
    """Есть ли на странице признаки прямого поставщика."""
    lowered = (text or "").lower()[:4000]
    return any(hint in lowered for hint in _DIRECT_HINTS)


_STOP_WORDS = frozenset(
    {
        "для", "или", "не", "от", "под", "при", "так", "это", "как", "на",
        "в", "с", "по", "из", "а", "и", "же", "ли", "у", "к", "о", "об",
    }
)


def requirement_text(req: Requirement) -> str:
    """Полный текст пункта ТЗ: название + описание.

    Documenter отдаёт короткий `name` («Регулятор давления») и подробный
    `value` («...фланцевый, проход 80 мм, давление 60,3 Мпа»). Характеристики
    лежат именно в значении, поэтому по одному названию агент искал
    «регулятор давления» и приносил газовые и пневматические.
    """
    parts = [req.title or "", req.description or ""]
    # Разделитель важен: без него первое слово description считалось
    # продолжением названия и исчезало из технических подсказок
    # («Регулятор давления Стальной» → терялось «стальной»).
    return "; ".join(p for p in parts if p).strip()


def _manufacturer_queries(requirements: list[Requirement]) -> list[str]:
    """Запросы фазы поиска производителей.

    Отдельная функция, чтобы след работы (trace.direct_queries) показывал
    реальные запросы второй фазы, а не пустой список.
    """
    prepared: list[tuple[str, str]] = []
    for req in requirements[:5]:
        core = extract_search_term(req.title, max_words=6)
        hints = extract_tech_hints(requirement_text(req))
        if core and all(core != existing[0] for existing in prepared):
            prepared.append((core, hints))
    if not prepared:
        return []
    queries: list[str] = []
    # Сначала запросы с характеристиками. Иначе общий «регулятор давления»
    # приносит газовые модели, хотя в ТЗ нужен 60,3 МПа, 80 мм, фланцевый.
    for core, hints in prepared:
        precise = f"{core} {hints}".strip()
        queries.append(f"{precise} {_MANUFACTURER_QUERY_SUFFIXES[0]}")
    for core, _hints in prepared:
        queries.append(f"{core} {_MANUFACTURER_QUERY_SUFFIXES[1]}")
    return list(dict.fromkeys(queries))[:6]


def extract_quantity(req: Requirement) -> int | None:
    """Количество позиции из ТЗ (например, ``10 шт.``)."""
    matches = re.findall(
        r"\b(\d{1,6})\s*(?:шт\.?|штук\w*)\b",
        requirement_text(req),
        re.IGNORECASE,
    )
    if not matches:
        return None
    values = [int(value) for value in matches if int(value) > 0]
    return values[-1] if values else None


def _normalized_evidence(text: str) -> str:
    return re.sub(r"[^а-яёa-z0-9]+", "", (text or "").lower().replace(",", "."))


def evidence_coverage(req: Requirement, evidence: str) -> tuple[int, int]:
    """Сколько ключевых характеристик ТЗ явно подтверждено источником."""
    hints = extract_tech_hints(requirement_text(req))
    parts = [m.group(0) for m in _TECH_HINTS.finditer(hints)]
    if not parts:
        return (0, 0)
    haystack = _normalized_evidence(evidence)
    matched = sum(1 for part in parts if _normalized_evidence(part) in haystack)
    return matched, len(parts)


def requirement_resolution_gaps(
    requirements: Sequence[Requirement],
    candidates: Sequence[SupplierCandidate],
) -> list[dict[str, Any]]:
    """Показать, почему каждая позиция ТЗ закрыта или остаётся нерешённой.

    Само название товара недостаточно. Для технической позиции карточка
    считается подтверждённой только когда источник содержит все извлечённые
    характеристики; после этого отдельно проверяется наличие цены.
    """
    gaps: list[dict[str, Any]] = []
    for req in requirements:
        req_text = requirement_text(req)
        related = [
            candidate
            for candidate in candidates
            if _tokens_overlap(req_text, f"{candidate.title} {candidate.evidence_text}")
        ]
        if not related:
            gaps.append(
                {
                    "code": req.code,
                    "title": req.title,
                    "status": "product_not_found",
                    "reason": "Товар не найден в конкретной карточке поставщика.",
                    "matched_specs": 0,
                    "total_specs": len(list(_TECH_HINTS.finditer(extract_tech_hints(req_text)))),
                }
            )
            continue

        coverage = [
            (*evidence_coverage(req, f"{candidate.title} {candidate.evidence_text}"), candidate)
            for candidate in related
        ]
        total_specs = max((total for _matched, total, _candidate in coverage), default=0)
        verified = [
            candidate
            for matched, total, candidate in coverage
            if total == 0 or matched == total
        ]
        best_matched = max((matched for matched, _total, _candidate in coverage), default=0)
        if total_specs and not verified:
            gaps.append(
                {
                    "code": req.code,
                    "title": req.title,
                    "status": "specifications_unconfirmed",
                    "reason": (
                        f"Карточка найдена, но подтверждено только {best_matched} "
                        f"из {total_specs} обязательных характеристик."
                    ),
                    "matched_specs": best_matched,
                    "total_specs": total_specs,
                }
            )
            continue

        if not any(candidate.price_kzt is not None for candidate in verified):
            gaps.append(
                {
                    "code": req.code,
                    "title": req.title,
                    "status": "price_unverified",
                    "reason": "Характеристики подтверждены, но проверенная цена не найдена.",
                    "matched_specs": total_specs,
                    "total_specs": total_specs,
                }
            )
            continue

        gaps.append(
            {
                "code": req.code,
                "title": req.title,
                "status": "resolved",
                "reason": "Товар, обязательные характеристики и цена подтверждены источником.",
                "matched_specs": total_specs,
                "total_specs": total_specs,
            }
        )
    return gaps


def recovery_query(req: Requirement, status: str, *, region_hint: str = "") -> str:
    """Один следующий запрос, направленный на конкретный пробел позиции."""
    core = extract_search_term(req.title) or req.title[:120]
    hints = extract_tech_hints(requirement_text(req))
    region = region_hint.strip() or "Казахстан"
    if status == "specifications_unconfirmed":
        suffix = "технические характеристики паспорт спецификация"
    elif status == "price_unverified":
        suffix = "цена купить тенге карточка товара"
    else:
        suffix = "поставщик купить карточка товара"
    return " ".join(part for part in (core, hints, suffix, region) if part).strip()


def relevant_evidence(text: str, terms: Sequence[str], *, limit: int = 5000) -> str:
    """Собрать короткие фрагменты страницы рядом с искомыми товарами."""
    if not text:
        return ""
    compact = re.sub(r"[ \t]+", " ", text)
    chunks: list[str] = []
    lowered = compact.lower()
    for term in terms:
        needle = (term or "").strip().lower()
        if len(needle) < 4:
            continue
        start = 0
        while len("\n".join(chunks)) < limit:
            index = lowered.find(needle, start)
            if index < 0:
                break
            chunks.append(compact[max(0, index - 220) : index + len(needle) + 520])
            start = index + len(needle)
            if len(chunks) >= 8:
                break
    if not chunks:
        chunks.append(compact[: min(limit, 1800)])
    return "\n…\n".join(dict.fromkeys(chunks))[:limit]


def _tokens_overlap(query: str, title: str) -> bool:
    """Есть ли значимое пересечение слов между запросом и пунктом ТЗ."""
    def _tokens(text: str) -> set[str]:
        words = re.findall(r"[а-яёa-z]{4,}", (text or "").lower())
        return {w for w in words if w not in _STOP_WORDS}

    q, t = _tokens(query), _tokens(title)
    return bool(q & t)


#: Слова-разделители, после которых в пункте ТЗ начинаются не название
#: товара, а характеристики/требования к нему.
_TERM_STOP_CHARS = (";", ",", " - ", " – ", " (", " [")

#: Характеристики, которые полезно вынести в отдельный поисковый запрос,
#: а не терять вместе с длинным названием.
_TECH_HINTS = re.compile(
    # Десятичная запятая обязательна: в ТЗ пишут «60,3 Мпа», а «\d+ мпа»
    # такую запись пропускал, и характеристика терялась.
    r"(\d+(?:[.,]\d+)?\s*(?:мпа|мм|см|кг|шт|бар|°с|кв|м³/ч|м3/ч|м³|м3|л/мин|об/мин))"
    r"|\b(фланцев\w*|стальн\w*|нержавеющ\w*|оцинкован\w*|маслозащ\w*|"
    r"водозащ\w*|промышленн\w*|строительн\w*|бытов\w*|автомобил\w*)",
    re.IGNORECASE,
)

#: Предлоги, с которых ядро названия не начинается: «для ДВС» в поиске
#: только мешает, а «Регулятор давления» находится без него.
_TERM_LEADING_PREPOSITIONS = frozenset({"для", "с", "из", "на", "по", "к", "от", "при"})


def extract_search_term(title: str, *, max_words: int = 4) -> str:
    """Достать номенклатурное ядро из пункта ТЗ.

    Пункт «Регулятор давления стальной, фланцевый, проход 80 мм, 60,3 Мпа»
    в поиске нужен как «Регулятор давления»: полная строка в запросе даёт
    мусорную выдачу и не находит ничего. Характеристики при этом не
    теряются — они попадают в отдельный запрос через ``extract_tech_hints``.
    """
    if not title:
        return ""
    head = title
    for sep in _TERM_STOP_CHARS:
        idx = head.find(sep)
        if idx > 0:
            head = head[:idx]
    head = head.strip(" -–—,")
    if not head:
        return ""
    words = [w for w in head.split() if w]
    # Убираем предлоги: «для ДВС», «с непосредственным впрыском» в поиске
    # только мешают — «Топливный фильтр» находится, а полная строка нет.
    # Убираем и ведущий, и внутренний, но не более одного предлога, чтобы
    # «стол офисный регулируемый» не превратился в «стол офисный».
    lead, tail = words[0], words[1:]
    keep: list[str] = [lead]
    for word in tail:
        bare = word.lower().strip(",;")
        if bare in _TERM_LEADING_PREPOSITIONS:
            break
        keep.append(word)
    return " ".join(keep[:max_words]).strip()


def _tokens_of(text: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]{3,}", (text or "").lower())


def extract_tech_hints(title: str) -> str:
    """Технические характеристики из пункта ТЗ — для точного запроса.

    «60,3 Мпа» и «фланцевый» отделяют нужный товар от сотен похожих;
    без них агент приносит газовые и пневматические регуляторы вместо
    стального фланцевого.
    """
    if not title:
        return ""
    numeric: list[str] = []
    words: list[str] = []
    # Сравниваем только с ядром названия: «фланцевый» в характеристиках
    # нужен, даже если где-то ещё в строке ТЗ встречается.
    seen = set(_tokens_of(extract_search_term(title)))
    for match in _TECH_HINTS.finditer(title):
        value = (match.group(1) or match.group(2) or "").strip()
        if not value or (set(_tokens_of(value)) & seen):
            continue
        if not _plausible_measurement(value):
            continue
        seen |= set(_tokens_of(value))
        # Числовые характеристики («60,3 Мпа», «80 мм») важнее словесных:
        # именно они отличают нужный товар от сотен похожих.
        (numeric if match.group(1) else words).append(value)
    return " ".join((numeric + words)[:4])


#: Правдоподобные границы для единиц измерения. Закупщики опечатываются
#: («4090°С» вместо «40–90°С»), и такое значение в поисковом запросе
#: гарантированно не находит нужный товар.
_MEASURE_LIMITS: tuple[tuple[str, float], ...] = (
    ("°с", 300.0),
    ("мпа", 100.0),
    ("бар", 1000.0),
    ("мм", 2000.0),
    ("см", 2000.0),
    ("м³", 500.0),
    ("м3", 500.0),
)


def _plausible_measurement(value: str) -> bool:
    """Не выглядит ли значение опечаткой в ТЗ.

    Мы не правим данные заказчика — мы просто не тащим очевидный мусор в
    поисковый запрос. Пользователь увидит исходное ТЗ в отчёте.
    """
    numbers = re.findall(r"\d+(?:[.,]\d+)?", value.replace(" ", ""))
    if not numbers:
        return True
    try:
        number = float(numbers[0].replace(",", "."))
    except ValueError:
        return True
    lowered = value.lower().replace(" ", "")
    for unit, limit in _MEASURE_LIMITS:
        if lowered.endswith(unit):
            return number <= limit
    return True


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Убрать повторы по URL, сохранив порядок."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in results:
        url = str(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
    return out


def find_contacts(text: str) -> tuple[str, str]:
    """Достать email и телефон из текста страницы.

    Только явные совпадения — выдумывать контакты нельзя, иначе агент
    отправит письмо несуществующему адресу.
    """
    if not text:
        return "", ""
    email_match = _EMAIL_RE.search(text)
    phone_match = _PHONE_RE.search(text)
    email = email_match.group(0) if email_match else ""
    phone = phone_match.group(0).strip() if phone_match else ""
    if not phone:
        # Номера вида 7801-31090-30 (flagma) идут без префикса +7/8.
        for candidate in _PHONE_KZ_RE.findall(text):
            digits = re.sub(r"\D", "", candidate)
            if len(digits) == 11:  # 7 + 10 цифр — казахстанский формат
                phone = candidate
                break
    # Отсекаем мусор: email из картинки/метрики и «телефон@домен».
    if email:
        local, _, domain = email.partition("@")
        # На страницах часто идёт «тел: 312-26-99info@company.kz» — почерк
        # съедает хвост номера. Отрезаем телефонный префикс до первой буквы.
        local = re.sub(r"^[\d\-\s()]{2,}(?=[A-Za-z])", "", local)
        if (
            not local
            or email.endswith((".png", ".jpg", ".webp"))
            or len(local) > 48
            or len(domain) > 64
            # Остаток не должен начинаться с длинного числового блока.
            or re.match(r"^\d{5,}", local)
        ):
            email = ""
        else:
            email = f"{local}@{domain}"
    return email, phone


def dedupe_requirements(items: Iterable[Any]) -> list[Requirement]:
    """Привести требования к единому виду, убрав дубли и пустые."""
    out: list[Requirement] = []
    seen: set[str] = set()
    for raw in items:
        if isinstance(raw, Requirement):
            req = raw
        elif isinstance(raw, dict):
            req = Requirement(
                code=str(raw.get("code") or "")[:64],
                title=str(raw.get("title") or "")[:512],
                description=str(raw.get("description") or "")[:2000],
                is_mandatory=bool(raw.get("is_mandatory")),
            )
        else:
            continue
        if not req.title:
            continue
        key = (req.title or req.code).strip().lower()[:120]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(req)
        if len(out) >= 25:
            break
    return out


def score_from_matches(matches: list[dict[str, Any]]) -> int:
    """Общий score 0–100. Вторичен: UI показывает статусы по пунктам (F2)."""
    if not matches:
        return 0
    weights = {MATCH_FITS: 1.0, MATCH_PARTIAL: 0.5, MATCH_UNKNOWN: 0.35, MATCH_NO: 0.0}
    total = sum(weights.get(str(m.get("status")), 0.0) for m in matches)
    return int(round(total / len(matches) * 100))


def normalize_match_status(status: Any) -> str:
    value = str(status or "").strip().lower()
    aliases = {
        "подходит": MATCH_FITS,
        "частично": MATCH_PARTIAL,
        "partial_fit": MATCH_PARTIAL,
        "не подходит": MATCH_NO,
        "нет данных": MATCH_UNKNOWN,
        "insufficient": MATCH_UNKNOWN,
        "": MATCH_UNKNOWN,
    }
    value = aliases.get(value, value)
    return value if value in VALID_MATCH_STATUSES else MATCH_UNKNOWN


def build_warnings(candidate: SupplierCandidate, requirements: list[Requirement]) -> list[str]:
    """Предупреждения, которые видит пользователь (F2)."""
    warnings: list[str] = []
    if not candidate.certificates:
        warnings.append("Сертификаты не указаны — запросите подтверждение.")
    if not candidate.warranty:
        warnings.append("Гарантия не указана.")
    if candidate.price_kzt is not None and not candidate.delivery_days:
        warnings.append("Цена указана без стоимости доставки.")
    if not candidate.email and not candidate.phone:
        warnings.append("Контакты на странице не найдены.")
    if candidate.is_middleman:
        warnings.append("Похоже на посредника, а не производителя — уточните, кто фактический поставщик.")
    if domain_country_hint(candidate.domain) == "foreign":
        warnings.append(
            "Зарубежный поставщик: уточните сроки и стоимость доставки, "
            "а также подходят ли документы для участия в тендере РК."
        )
    if candidate.domain_kind == "direct" and not candidate.is_middleman:
        # Прямой поставщик — контакты и цена производителя, а не витрины.
        if not candidate.email and not candidate.phone:
            warnings.append("Сайт похож на сайт компании — контакты искать в разделах «Контакты» и «О нас».")
    mandatory = [r for r in requirements if r.is_mandatory]
    if mandatory:
        misses = sum(
            1
            for r in mandatory
            for m in candidate.requirement_matches
            if m.get("code") == r.code and m.get("status") in {MATCH_NO, MATCH_UNKNOWN}
        )
        if misses:
            warnings.append(f"Не подтверждено обязательных пунктов: {misses}.")
    # Дедупликация с сохранением порядка.
    seen: set[str] = set()
    unique: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique


class SupplierAgent(Agent):
    """Ищет поставщиков по требованиям лота и сверяет их с ТЗ."""

    name = "supplier_agent"

    system_prompt = """Ты — помощник по закупкам в Казахстане. Твоя задача — найти
компании, которые поставляют нужный товар, и честно проверить их по пунктам ТЗ.

Правила, которые нельзя нарушать:
1. Если характеристика не найдена — ставь статус "unknown" (нет данных).
   Никогда не выдумывай характеристики, цены, сертификаты и контакты.
2. Для каждого статуса указывай source_url — страницу, где взята информация.
3. Статусы: fits (подходит) / partial (подходит частично) /
   no (не подходит) / unknown (нет данных).
4. Если товар — посредник, а производитель другой — укажи это в warnings.
5. Сайт производителя или дилера ценнее маркетплейса: на нём есть реальные
   контакты, оптовые цены и сертификаты. Отмечай такие в supplier_type.

Сначала верни JSON со search_queries: 3–7 поисковых запросов (казахский и
русский), по которым реально можно найти поставщика.

Формат ответа:
{
  "search_queries": ["..."],
  "suppliers": [
    {
      "supplier": "Название компании",
      "domain": "example.kz",
      "title": "Название товара/услуги",
      "url": "https://...",
      "price_kzt": 45000,
      "in_stock": true,
      "city": "Астана",
      "delivery_days": 5,
      "email": "",
      "phone": "",
      "certificates": ["ISO 9001"],
      "warranty": "12 месяцев",
      "requirement_matches": [
        {"code": "1.1", "title": "...", "status": "fits",
         "comment": "производитель, сталь 304", "source_url": "https://..."}
      ],
      "warnings": []
    }
  ]
}"""

    def __init__(self) -> None:
        self._tavily_client = None
        self._browser_agent = None
        settings = get_settings()
        tavily_key = getattr(settings, "tavily_api_key", None)
        if tavily_key:
            try:
                from tavily import TavilyClient

                self._tavily_client = TavilyClient(api_key=tavily_key)
            except Exception as exc:  # pragma: no cover - внешняя зависимость
                logger.warning("[supplier] Tavily init failed: {}", exc)
        browser_key = getattr(settings, "browser_use_api_key", None)
        if browser_key:
            try:
                from app.agents.browser_use import BrowserUseAgent

                self._browser_agent = BrowserUseAgent(api_key=browser_key)
            except Exception as exc:  # pragma: no cover - внешняя зависимость
                logger.warning("[supplier] Browser-Use init failed: {}", exc)

    # ── Шаг 1: поисковые запросы ──────────────────────────────────────
    #: Шаблоны формулировок. Поисковая выдача зависит от формулировки
    #: сильно: одна и та же позиция находится и по названию, и по
    #: «оптом», и по казахскому термину. Один запрос сужает выдачу и
    #: теряет поставщиков, поэтому пробуем несколько вариантов.
    QUERY_TEMPLATES: tuple[str, ...] = (
        "{title}",
        "{title} купить Казахстан",
        "{title} оптом поставщик",
        "{title} цена прайс Казахстан",
        "{title} производитель дилер",
        "{title} сатып алушы Қазақстан",
    )

    async def build_queries(
        self,
        requirements: list[Requirement],
        *,
        budget_kzt: float | None = None,
        variants_per_item: int = 2,
        region_hint: str = "",
        company_terms: Sequence[str] = (),
    ) -> tuple[list[str], Costs]:
        """Попросить LLM поисковые запросы и разнообразить шаблонами.

        ``variants_per_item`` — сколько разных формулировок пробовать на
        каждый пункт ТЗ. Больше вариантов — шире охват, но дороже.

        Запросы строятся на номенклатурном ядре пункта ТЗ, а не на всей
        строке: «Регулятор давления стальной, фланцевый, проход 80 мм» в
        поиске не работает, «Регулятор давления» — работает. Характеристики
        при этом не теряются, а уходят в отдельный точный запрос.
        """
        costs = Costs()
        if not requirements:
            return [], costs
        req_lines = "\n".join(
            f"- {r.title}" + (f" ({r.description[:200]})" if r.description else "")
            for r in requirements[:8]
        )
        region_note = f"Регион поставки: {region_hint}\n" if region_hint else ""
        company_note = ""
        if company_terms:
            company_note = f"Профиль компании, релевантный запросу: {', '.join(company_terms)}\n"
        prompt = (
            "Пункты ТЗ, по которым нужно найти поставщика:\n"
            f"{req_lines}\n\n"
            f"Бюджет: {budget_kzt if budget_kzt else 'не указан'} тг\n"
            f"{region_note}{company_note}\n"
            "Составь 3–7 поисковых запросов: товар + синонимы + ключевые характеристики, "
            "на русском и казахском языках. Верни JSON {\"queries\": [...]}."
        )
        data = await self._chat_json(prompt, max_tokens=800)
        costs.llm_usd += 0.0002
        costs.llm_calls += 1
        llm_queries = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]

        # Ядро названия вместо первых 80 символов пункта ТЗ.
        cores: list[str] = []
        for req in requirements:
            core = extract_search_term(req.title)
            if core and core not in cores:
                cores.append(core)
            if len(cores) >= 3:
                break
        if not cores:
            cores = [extract_search_term(q, max_words=5) or q[:80] for q in llm_queries[:3]]
        cores = [c for c in cores if c][:3]
        if not cores or not cores[0]:
            return llm_queries[:7], costs

        variants: list[str] = []
        # Точные характеристики ставим ПЕРВЫМИ. Раньше они добавлялись в
        # конец, а search_web обрезал список до семи запросов: запрос
        # «60,3 МПа, 80 мм, фланцевый» фактически не выполнялся.
        def _hint_weight(req: Requirement) -> tuple[int, int]:
            hints = extract_tech_hints(requirement_text(req))
            numeric = len(re.findall(r"\d", hints))
            return (1 if numeric else 0, numeric)

        precise_targets = sorted(
            [r for r in requirements if extract_tech_hints(requirement_text(r))],
            key=_hint_weight,
            reverse=True,
        )[:5]
        for req in precise_targets:
            hints = extract_tech_hints(requirement_text(req))
            core = extract_search_term(req.title)
            if not hints or not core:
                continue
            precise = f"{core} {hints}"
            variants.append(precise)
            if region_hint:
                variants.append(f"{precise} {region_hint}")

        # Затем формулировки модели и устойчивые шаблоны.
        variants.extend(q for q in llm_queries if any(
            _tokens_overlap(q, term) for term in cores
        ) and q not in variants)
        # Затем шаблонные варианты по каждому пункту. Их ограничиваем так,
        # чтобы в лимит поместились ещё точный запрос с характеристиками и
        # региональный — без них технические пункты ТЗ не закрываются.
        for term in cores:
            for template in self.QUERY_TEMPLATES:
                candidate = template.format(title=term).strip()
                if candidate and candidate not in variants:
                    variants.append(candidate)
                if sum(1 for v in variants if _tokens_overlap(v, term)) >= variants_per_item + 1:
                    break

        # Регион лота в запросы: поставка в Казахстан из другой страны —
        # это другая логистика и другая цена.
        if region_hint:
            for term in cores[:2]:
                regional = f"{term} {region_hint}"
                if regional not in variants:
                    variants.append(regional)

        # Лимит: не меньше шести запросов, иначе в выдачу не попадают ни
        # точный запрос с характеристиками, ни региональный — а именно
        # они закрывают технические пункты ТЗ.
        limit = max(6, min(10, variants_per_item * len(cores) + len(cores) + 2))
        return variants[:limit], costs

    # ── Шаг 2: Tavily ────────────────────────────────────────────────
    async def search_web(
        self,
        queries: list[str],
        *,
        max_results: int = 20,
        domains: Sequence[str] | None = DEFAULT_SEARCH_DOMAINS,
        max_calls: int | None = None,
    ) -> tuple[list[dict[str, Any]], Costs]:
        """Поиск в интернете. Без Tavily возвращает пустой список, а не выдумку.

        ``domains=None`` означает поиск по всему интернету — так находится
        сайт самого производителя, а не витрина маркетплейса.
        """
        costs = Costs()
        if not self._tavily_client:
            logger.info("[supplier] Tavily не сконфигурирован — поиск пропущен")
            return [], costs

        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        # build_queries уже ограничивает набор десятью запросами. Выполняем
        # весь видимый trace, чтобы trace не утверждал, что точный запрос
        # был сделан, когда он на самом деле был обрезан.
        call_limit = max(0, min(10, max_calls if max_calls is not None else 10))
        for query in queries[:call_limit]:
            costs.tavily_attempts += 1
            try:
                kwargs: dict[str, Any] = {
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 10,
                }
                if domains:
                    kwargs["include_domains"] = list(domains)
                response = self._tavily_client.search(**kwargs)
            except Exception as exc:
                logger.warning("[supplier] Tavily search failed for '{}': {}", query, exc)
                continue
            # ~$0.008 за запрос (средняя оценка по тарифам Tavily).
            costs.tavily_usd += 0.008
            costs.tavily_calls += 1
            for item in response.get("results", []):
                url = str(item.get("url") or "")
                if not url or url in seen:
                    continue
                seen.add(url)
                collected.append(
                    {
                        "title": str(item.get("title") or "")[:512],
                        "url": url[:1000],
                        "content": str(item.get("content") or "")[:1500],
                        "score": float(item.get("score") or 0.0),
                    }
                )
        collected.sort(key=lambda r: r["score"], reverse=True)
        return collected[:max_results], costs

    # ── Шаг 2b: поиск прямых производителей в открытом веб-поиске ──
    async def search_manufacturers(
        self,
        requirements: list[Requirement],
        *,
        max_results: int = 12,
        max_calls: int | None = None,
    ) -> tuple[list[dict[str, Any]], Costs]:
        """Найти сайты производителей и дилеров без ограничения доменов.

        Зачем вторая фаза: маркетплейсы (Kaspi, OLX, Flagma) не дают
        контакты и цену производителя, а на сайте самого завода они есть
        почти всегда. Маркетплейс остаётся быстрым способом сравнить цены,
        но прямой поставщик — это то, что реально можно связаться.
        """
        costs = Costs()
        if not self._tavily_client or not requirements:
            return [], costs

        # Запросы строим из номенклатурного ядра + подсказка «производитель/оптом».
        queries = _manufacturer_queries(requirements)
        if not queries:
            return [], costs

        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        call_limit = max(0, min(len(queries), max_calls if max_calls is not None else len(queries)))
        for query in queries[:call_limit]:
            costs.tavily_attempts += 1
            try:
                # Без include_domains — ищем сайты компаний по всему вебу.
                response = self._tavily_client.search(
                    query=query,
                    search_depth="basic",
                    max_results=8,
                )
            except Exception as exc:
                logger.warning("[supplier] manufacturer search failed: {}", exc)
                continue
            costs.tavily_usd += 0.008  # ~$0.008 за запрос
            costs.tavily_calls += 1
            for item in response.get("results", []):
                url = str(item.get("url") or "")
                if not url or url in seen:
                    continue
                domain = extract_domain(url)
                kind = classify_domain(domain)
                # Соцсети и доски объявлений бесполезны: контактов там нет.
                if kind == "classifieds":
                    continue
                seen.add(url)
                content = str(item.get("content") or "")[:1500]
                direct = kind == "direct" and looks_like_manufacturer(content)
                collected.append(
                    {
                        "title": str(item.get("title") or "")[:512],
                        "url": url[:1000],
                        "content": content,
                        "domain_kind": kind,
                        # Прямого производителя поднимаем выше площадки.
                        "score": float(item.get("score") or 0.0) + (0.5 if direct else 0.0),
                    }
                )
        collected.sort(key=lambda r: r["score"], reverse=True)
        return collected[:max_results], costs

    # ── Шаг 3a: бесплатное чтение страниц (Jina → Tavily) ─────────
    async def enrich_with_pages(
        self,
        candidates: list[SupplierCandidate],
        *,
        top_n: int = 10,
        terms: Sequence[str] = (),
    ) -> Costs:
        """Прочитать страницы поставщиков и достать контакты/цену.

        Идёт перед платным Browser-Use: Jina Reader бесплатен и рендерит
        JavaScript, поэтому в большинстве случаев платить не нужно вовсе.
        """
        from app.agents.page_fetcher import fetch_page

        costs = Costs()
        for candidate in candidates[:top_n]:
            if not candidate.url:
                continue
            # Сначала микроразметка: цена в itemprop="price" надёжнее
            # разбора видимого текста, потому что не зависит от вёрстки
            # и не путает цену соседнего товара на странице-каталоге.
            await self._apply_structured_prices(candidate, terms)
            page = await fetch_page(candidate.url)
            if not page.is_usable:
                logger.info(
                    "[supplier] страница не прочитана ({}): {}",
                    page.provider,
                    page.error or "empty",
                )
                if page.error in {"captcha", "bot_check", "js_required", "access_denied"}:
                    # Это анти-бот, а не пустая страница: платный браузер
                    # тут единственный оставшийся путь.
                    candidate.warnings.append(
                        "Сайт закрыт анти-ботом — нужен браузерный режим."
                    )
                else:
                    candidate.warnings.append("Страницу поставщика не удалось прочитать.")
                continue
            costs.page_fetch_count += 1
            self._apply_page_text(candidate, page.text, terms=terms)
        return costs

    async def _apply_structured_prices(
        self, candidate: SupplierCandidate, terms: Sequence[str]
    ) -> None:
        """Взять цену и наличие из микроразметки страницы.

        Отдельный быстрый HTTP-запрос к самому сайту: разметка лежит в
        HTML, который Jina Reader отдаёт уже как markdown и теряет.
        """
        if candidate.price_kzt is not None or not candidate.url:
            return
        from app.agents.page_fetcher import is_public_http_url
        from app.agents.structured_data import extract_products, pick_price

        if not is_public_http_url(candidate.url):
            return
        try:
            import httpx

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=8.0), follow_redirects=True
            ) as client:
                response = await client.get(
                    candidate.url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; TendrBot/1.0)",
                        "Accept-Language": "ru-KZ,ru;q=0.9",
                    },
                )
            if response.status_code >= 400:
                return
            html = response.text
        except Exception as exc:  # noqa: BLE001 — внешний сайт, тихо продолжаем
            logger.debug("[supplier] не удалось взять микроразметку {}: {}", candidate.url, exc)
            return

        products = extract_products(html)
        if not products:
            return
        # Сначала по ядрам из ТЗ, затем по названию карточки.
        for term in list(terms) + [candidate.title]:
            if not term:
                continue
            price = pick_price(products, term)
            if price:
                candidate.price_kzt = float(price)
                candidate.sources["price"] = candidate.url
                candidate.sources["price_source"] = "structured_data"
                matched = next(
                    (p for p in products if p.in_stock is not None), None
                )
                if matched is not None and candidate.in_stock is None:
                    candidate.in_stock = matched.in_stock
                return

    def _apply_page_text(
        self,
        candidate: SupplierCandidate,
        text: str,
        *,
        terms: Sequence[str] = (),
    ) -> None:
        """Разобрать текст страницы: контакты, цена, наличие, город.

        ``terms`` — номенклатурные ядра из пунктов ТЗ. Цена ищется рядом с
        ними, а не только рядом с заголовком карточки: на странице-каталоге
        заголовок это рубрика («Топливные фильтры тонкой очистки»), а товары
        с ценами идут ниже. Без этого каталоги всегда давали цену None.
        """
        from app.agents.supplier_agent import find_contacts

        email, phone = find_contacts(text)
        if email and not candidate.email:
            candidate.email = email
            candidate.sources["email"] = candidate.url
        if phone and not candidate.phone:
            candidate.phone = phone
            candidate.sources["phone"] = candidate.url

        page_evidence = relevant_evidence(text, list(terms) + [candidate.title])
        if page_evidence:
            candidate.evidence_text = page_evidence

        if candidate.price_kzt is None:
            # Цену берём ТОЛЬКО рядом с названием товара — того самого, который
            # искали. На каталоге из десяти позиций первая цена на странице
            # почти всегда принадлежит другому товару, и раньше агент
            # приписывал поставщику чужую цену (например «123 ₸» за фильтр).
            #
            # Сначала ищем по номенклатурным ядрам из ТЗ: заголовок карточки
            # на каталоге — это рубрика («Топливные фильтры тонкой очистки»),
            # и цена рядом с ней принадлежит соседнему товару.
            price = None
            if terms:
                price = self._price_near_terms(text, terms)
            if price is None:
                price = self._price_near_title(candidate.title, text)
            if price is not None:
                candidate.price_kzt = price
                candidate.sources["price"] = candidate.url

        if candidate.in_stock is None and re.search(
            r"\b(в наличии|есть в наличии|instock|на складе)\b", text, re.IGNORECASE
        ):
            candidate.in_stock = True

        if not candidate.city:
            match = re.search(
                r"(Астана|Алматы|Павлодар|Караганда|Шымкент|Актобе|Тараз|Костанай|"
                r"Петропавловск|Семей|Орал|Кызылорда|Атырау|Темиртау|Актолай)",
                text,
            )
            if match:
                candidate.city = match.group(1)

    @classmethod
    def _price_near_terms(cls, text: str, terms: Sequence[str]) -> float | None:
        """Найти цену нужного товара на странице-каталоге.

        Разбор построчный: цена берётся из строки, где названо искомое
        слово, либо из следующей строки (на каталогах название и цена часто
        разнесены). Так «Топливный фильтр — 107 000 тенге» даёт свою цену,
        а не цену соседнего сепаратора за 1 176 000.

        Тот же принцип честности, что в ``_price_near_title``: цена
        принадлежит только тому, рядом с чем написано название искомого
        товара. Отличие — название ищется в тексте страницы, а не среди
        заголовков карточки (на каталоге заголовок это рубрика).
        """
        if not text or not terms:
            return None
        from app.agents.product_search import _parse_price

        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]

        def _price_in(chunk: str) -> float | None:
            best: float | None = None
            for match in PRICE_RE.finditer(chunk):
                parsed = _parse_price(match.group(1))
                if parsed and parsed > 0 and (best is None or parsed < best):
                    best = parsed
            return best

        for term in terms:
            needle = re.sub(r"\s+", " ", term.strip().lower())
            if len(needle) < 4:
                continue
            for index, line in enumerate(lines):
                hay = line.lower()
                if needle not in hay:
                    continue
                # Цена в той же строке.
                price = _price_in(line)
                if price is not None:
                    return price
                # Или в следующих строках, пока не начался другой товар.
                for follow in lines[index + 1 : index + 3]:
                    price = _price_in(follow)
                    if price is not None:
                        return price
                    # Новая строка-заголовок без цены — товар сменился.
                    if len(follow) > 3 and not PRICE_MARKER_RE.search(follow):
                        break
        return None

    @staticmethod
    def _price_near_title(title: str, text: str) -> float | None:
        """Найти цену рядом с названием товара.

        Возвращает ``None``, если название не найдено или рядом нет цены:
        честное «не знаю» лучше чужой цены.
        """
        if not title or not text:
            return None
        from app.agents.product_search import _parse_price

        needle = re.sub(r"\s+", " ", title.strip().lower())
        # Длинные названия обрезаем: в каталоге заголовок может обрываться.
        needles = [needle] if len(needle) <= 60 else [needle[:60], needle[:40]]
        haystack = text.lower()
        pos = -1
        for candidate_needle in needles:
            pos = haystack.find(candidate_needle)
            if pos != -1:
                break
        if pos == -1:
            return None
        window = text[pos : pos + PRICE_WINDOW]
        # Обрезаем по началу следующей карточки: цена соседнего товара
        # не должна приписываться нашему поставщику.
        next_card = re.search(r"\n\s*#{1,3}\s", window[1:])
        if next_card:
            window = window[: next_card.start() + 1]
        best: float | None = None
        for match in PRICE_RE.finditer(window):
            parsed = _parse_price(match.group(1))
            if parsed and parsed > 0 and (best is None or parsed > best):
                best = parsed
        return best

    # ── Шаг 3b: Browser-Use — платный запасной вариант ────────────
    async def enrich_with_browser(
        self, candidates: list[SupplierCandidate], *, top_n: int = 3
    ) -> Costs:
        """Зайти на сайт и добрать контакты/цену/наличие.

        Дорого, поэтому только топ-N. Любая ошибка — предупреждение, а не падение.
        """
        costs = Costs()
        if self._browser_agent is None:
            return costs
        for candidate in candidates[:top_n]:
            if not candidate.url:
                continue
            task = (
                f"Зайди на {candidate.url}. Найди карточку товара «{candidate.title}». "
                "Собери: актуальную цену в тенге, наличие, город и сроки доставки, "
                "контакты (email и телефон), сертификаты и гарантию. "
                "Верни JSON с полями price_kzt, in_stock, city, delivery_days, "
                "email, phone, certificates, warranty. "
                "НЕ оформляй заказ и НЕ вводи никаких персональных данных."
            )
            try:
                result = await self._browser_agent.run_task(
                    task=task,
                    model="gpt-5.4-mini",
                    proxy_country="kz",
                    allowed_domains=[candidate.domain] if candidate.domain else None,
                    enable_recording=False,
                    max_duration_min=5,
                )
            except Exception as exc:
                logger.warning("[supplier] browser enrich failed for {}: {}", candidate.url, exc)
                candidate.warnings.append("Не удалось проверить страницу поставщика.")
                continue
            costs.browser_calls += 1
            costs.browser_usd += float(getattr(result, "cost_usd", 0.0) or 0.0)
            output = getattr(result, "output", None)
            if not isinstance(output, dict):
                continue
            self._merge_browser_output(candidate, output)
        return costs

    @staticmethod
    def _merge_browser_output(candidate: SupplierCandidate, output: dict[str, Any]) -> None:
        price = output.get("price_kzt")
        if price is not None:
            try:
                candidate.price_kzt = float(price)
                candidate.sources["price"] = candidate.url
            except (TypeError, ValueError):
                pass
        if isinstance(output.get("in_stock"), bool):
            candidate.in_stock = output["in_stock"]
        if output.get("city"):
            candidate.city = str(output["city"])[:128]
        days = output.get("delivery_days")
        if days is not None:
            try:
                candidate.delivery_days = int(days)
            except (TypeError, ValueError):
                pass
        if output.get("email"):
            candidate.email = str(output["email"])[:255]
            candidate.sources["email"] = candidate.url
        if output.get("phone"):
            candidate.phone = str(output["phone"])[:32]
            candidate.sources["phone"] = candidate.url
        if isinstance(output.get("certificates"), list):
            candidate.certificates = [str(c)[:128] for c in output["certificates"]][:10]
        if output.get("warranty"):
            candidate.warranty = str(output["warranty"])[:256]

    # ── Шаг 4: сверка по пунктам ТЗ ──────────────────────────────────
    async def match_requirements(
        self, candidates: list[SupplierCandidate], requirements: list[Requirement]
    ) -> Costs:
        """LLM сверяет кандидатов с пунктами ТЗ и проставляет статусы."""
        costs = Costs()
        if not candidates or not requirements:
            for candidate in candidates:
                candidate.score = 0
                candidate.warnings = build_warnings(candidate, requirements)
            return costs

        req_block = "\n".join(
            f"[{r.code or r.title[:32]}] {r.title}"
            + (f" — {r.description[:700]}" if r.description else "")
            + (" — обязательный" if r.is_mandatory else "")
            for r in requirements[:20]
        )
        for candidate in candidates:
            prompt = (
                f"Пункты ТЗ:\n{req_block}\n\n"
                f"Карточка поставщика:\n"
                f"Компания: {candidate.supplier}\n"
                f"Товар: {candidate.title}\n"
                f"Цена: {candidate.price_kzt}\n"
                f"Наличие: {candidate.in_stock}\n"
                f"Город: {candidate.city}\n"
                f"Сертификаты: {candidate.certificates}\n"
                f"Гарантия: {candidate.warranty}\n"
                f"Источник: {candidate.url}\n\n"
                f"Фрагмент источника:\n{candidate.evidence_text[:6000] or 'нет текста страницы'}\n\n"
                "Верни JSON {\"requirement_matches\": [{\"code\": \"...\", "
                "\"title\": \"...\", \"status\": \"fits|partial|no|unknown\", "
                "\"comment\": \"...\", \"source_url\": \"...\"}]}."
                "Если данных нет — status=unknown, а не догадка."
            )
            data = await self._chat_json(prompt, max_tokens=1500)
            costs.llm_usd += 0.0005
            costs.llm_calls += 1
            matches: list[dict[str, Any]] = []
            for raw in data.get("requirement_matches", []) or []:
                if not isinstance(raw, dict):
                    continue
                code = str(raw.get("code") or "")
                title = str(raw.get("title") or "")
                # Сопоставляем с исходным пунктом, чтобы не потерять код.
                known = next(
                    (r for r in requirements if code and code == r.code),
                    None,
                ) or next((r for r in requirements if title and title == r.title), None)
                match = {
                        "code": known.code if known else code[:64],
                        "title": (known.title if known else title)[:512],
                        "status": normalize_match_status(raw.get("status")),
                        "comment": str(raw.get("comment") or "")[:1000],
                        "source_url": candidate.url,
                    }
                # Статус «подходит» допустим только при доказательстве на
                # реальной странице. Модель не может додумать 60,3 МПа,
                # фланец или 80 мм из одного заголовка каталога.
                if known and match["status"] in {MATCH_FITS, MATCH_PARTIAL}:
                    evidence = f"{candidate.title} {candidate.evidence_text}"
                    covered_hints, total_hints = evidence_coverage(known, evidence)
                    if total_hints and covered_hints < total_hints:
                        match["status"] = MATCH_PARTIAL if covered_hints else MATCH_UNKNOWN
                        match["comment"] = (
                            f"Источник подтверждает {covered_hints} из {total_hints} "
                            "ключевых характеристик ТЗ. Требуется подтверждение поставщика."
                        )
                matches.append(match)
            # Пункты, о которых LLM не сказала, — честно «нет данных».
            covered = {m["code"] for m in matches if m.get("code")}
            for req in requirements:
                if req.code and req.code not in covered:
                    matches.append(
                        {
                            "code": req.code,
                            "title": req.title[:512],
                            "status": MATCH_UNKNOWN,
                            "comment": "Нет данных от поставщика.",
                            "source_url": candidate.url,
                        }
                    )
            candidate.requirement_matches = matches
            candidate.score = score_from_matches(matches)
            candidate.is_middleman = candidate.domain in MIDDLEMAN_DOMAINS
            existing_warnings = list(candidate.warnings)
            candidate.warnings = list(
                dict.fromkeys(existing_warnings + build_warnings(candidate, requirements))
            )

        return costs

    # ── Оркестрация ──────────────────────────────────────────────────
    async def run(
        self,
        requirements: list[Requirement],
        *,
        budget_kzt: float | None = None,
        blocked: set[str] | None = None,
        enrich_browser: bool = True,
        page_fetch_top_n: int = 10,
    ) -> list[SupplierCandidate]:
        """Точка входа агента (контракт Agent.run).

        Возвращает только кандидатов; расходы и метаданные доступны через
        find_suppliers, которому нужен аудит.
        """
        candidates, _costs, _meta = await self.find_suppliers(
            requirements,
            budget_kzt=budget_kzt,
            blocked=blocked,
            enrich_browser=enrich_browser,
            page_fetch_top_n=page_fetch_top_n,
        )
        return candidates

    def _queries_by_requirement(
        self, requirements: list[Requirement], shared: list[str]
    ) -> list[list[str]]:
        """Разложить запросы по пунктам ТЗ.

        Если запросов меньше, чем пунктов, добираем поиском по названию
        пункта — так ни одна позиция лота не останется без поставщиков.
        """
        groups: list[list[str]] = []
        for req in requirements[:5]:
            own = [q for q in shared if _tokens_overlap(q, req.title)]
            hints = extract_tech_hints(requirement_text(req))
            if hints:
                hint_markers = [
                    _normalized_evidence(match.group(0))
                    for match in _TECH_HINTS.finditer(hints)
                ]
                own.sort(
                    key=lambda q: (
                        -sum(marker in _normalized_evidence(q) for marker in hint_markers),
                        len(q),
                        q.lower(),
                    )
                )
            if own:
                groups.append(own[:2])
                continue
            groups.append([req.title[:120]])
        return groups

    async def find_suppliers(
        self,
        requirements: list[Requirement],
        *,
        budget_kzt: float | None = None,
        blocked: set[str] | None = None,
        enrich_browser: bool = True,
        page_fetch_top_n: int = 10,
        query_variants: int = 2,
        region_hint: str = "",
        company_terms: Sequence[str] = (),
        perform_matching: bool = True,
    ) -> tuple[list[SupplierCandidate], Costs, dict[str, Any]]:
        """Полный конвейер F1+F2. Возвращает кандидатов, расходы и метаданные."""
        requirements = dedupe_requirements(requirements)
        total = Costs()
        max_search_calls = max(1, min(20, int(get_settings().supplier_search_max_calls)))
        meta: dict[str, Any] = {
            "queries": [],
            "direct_queries": [],
            "planned_queries": [],
            "search_call_limit": max_search_calls,
            "search_calls_attempted": 0,
            "resolution_gaps": [],
            "candidates_count": 0,
            "blocked_filtered": 0,
        }

        if not requirements:
            return [], total, meta

        queries, costs = await self.build_queries(
            requirements,
            budget_kzt=budget_kzt,
            variants_per_item=query_variants,
            region_hint=region_hint,
            company_terms=company_terms,
        )
        total.merge(costs)
        meta["planned_queries"] = queries
        if not queries:
            return [], total, meta

        # Лот часто мультипозиционный. Если искать по всем запросам разом,
        # позиционный товар «съедает» лимит: на живом прогоне лота
        # «фильтр + регулятор давления» все 20 мест ушли поставщикам
        # фильтров, и по регулятору не осталось никого.
        # Поэтому каждый пункт ТЗ получает свою квоту результатов.
        per_item_queries = self._queries_by_requirement(requirements, queries)
        results: list[dict[str, Any]] = []
        executed_queries: list[str] = []
        per_item_quota = max(3, 20 // max(1, len(per_item_queries)))
        # Первый круг даёт каждой позиции ровно одну технически точную
        # попытку. Остаток бюджета сохраняется для адресного повторного
        # поиска после проверки фактических карточек.
        for item_queries in per_item_queries:
            if total.tavily_attempts >= max_search_calls:
                break
            attempt = item_queries[:1]
            found, costs = await self.search_web(
                attempt,
                max_results=per_item_quota,
                max_calls=1,
            )
            total.merge(costs)
            executed_queries.extend(attempt[: costs.tavily_attempts])
            results.extend(found)
        results = _dedupe_results(results)[:20]
        meta["queries"] = executed_queries

        blocked = blocked or set()
        candidates: list[SupplierCandidate] = []
        # Приоритет: прямой поставщик важнее витрины. Без этой сортировки
        # маркетплейсы забивают лимит 20 первыми, и сайты производителей
        # (а именно там есть контакты) до него не доходят.
        def _priority(item: dict[str, Any]) -> tuple[int, int, float, str, str]:
            domain = extract_domain(item["url"])
            kind = str(item.get("domain_kind") or classify_domain(domain))
            # 0 — прямой поставщик, 1 — агрегатор/неизвестно
            # Внутри группы приоритет казахстанским доменам: закупка в КЗ
            # без перекрёстной логистики и с местными документами.
            country_rank = {"kz": 0, "neutral": 1, "foreign": 2}.get(
                domain_country_hint(domain), 1
            )
            return (
                0 if kind == "direct" else 1,
                country_rank,
                -float(item.get("score") or 0.0),
                domain,
                str(item.get("url") or ""),
            )

        known_urls: set[str] = set()
        search_terms = [
            core
            for core in dict.fromkeys(extract_search_term(r.title) for r in requirements)
            if core
        ]

        def _append_results(items: Sequence[dict[str, Any]]) -> list[SupplierCandidate]:
            added: list[SupplierCandidate] = []
            for item in sorted(items, key=_priority):
                url = str(item.get("url") or "")
                if not url or url in known_urls or len(candidates) >= 20:
                    continue
                known_urls.add(url)
                domain = extract_domain(url)
                supplier = str(item.get("title") or "")[:256] or domain
                if supplier in blocked or domain in blocked:
                    meta["blocked_filtered"] += 1
                    continue
                kind = str(item.get("domain_kind") or classify_domain(domain))
                if kind == "classifieds":
                    continue
                content = str(item.get("content") or "")[:5000]
                email, phone = find_contacts(content)
                candidate = SupplierCandidate(
                    supplier=supplier,
                    domain=domain,
                    title=str(item.get("title") or "")[:512],
                    url=url,
                    email=email,
                    phone=phone,
                    is_middleman=kind == "aggregator",
                    domain_kind=kind,
                    evidence_text=content,
                )
                candidate.sources["search"] = url
                # Цена из фрагмента считается подтверждённой только когда
                # находится рядом с названием позиции, а не в соседней карточке.
                self._apply_page_text(candidate, content, terms=search_terms)
                candidates.append(candidate)
                added.append(candidate)
            return added

        initial_candidates = _append_results(results)

        # Сначала бесплатное чтение страниц, потом (если нужно) платный браузер.
        if enrich_browser and initial_candidates:
            costs = await self.enrich_with_pages(
                initial_candidates,
                top_n=min(page_fetch_top_n, len(initial_candidates)),
                terms=search_terms,
            )
            total.merge(costs)

        # Проверяем каждую позицию до того, как тратить оставшийся поиск.
        # Страница с одним названием не закрывает регулятор, если на ней нет
        # 60,3 МПа, материала и типа соединения.
        gaps = requirement_resolution_gaps(requirements, candidates)
        unresolved = [gap for gap in gaps if gap["status"] != "resolved"]
        remaining_calls = max(0, max_search_calls - total.tavily_attempts)
        recovery_queries: list[str] = []
        for gap in unresolved:
            if len(recovery_queries) >= remaining_calls:
                break
            req = next(
                (item for item in requirements if item.code == gap["code"]),
                None,
            )
            if req is None:
                continue
            query = recovery_query(req, str(gap["status"]), region_hint=region_hint)
            if query and query not in recovery_queries and query not in executed_queries:
                recovery_queries.append(query)

        if recovery_queries:
            recovery_results, costs = await self.search_web(
                recovery_queries,
                domains=None,
                max_results=max(3, 20 - len(candidates)),
                max_calls=remaining_calls,
            )
            total.merge(costs)
            meta["direct_queries"] = recovery_queries[: costs.tavily_attempts]
            recovered_candidates = _append_results(recovery_results)
            if enrich_browser and recovered_candidates:
                costs = await self.enrich_with_pages(
                    recovered_candidates,
                    top_n=min(page_fetch_top_n, len(recovered_candidates)),
                    terms=search_terms,
                )
                total.merge(costs)
            gaps = requirement_resolution_gaps(requirements, candidates)

        meta["resolution_gaps"] = gaps
        meta["search_calls_attempted"] = total.tavily_attempts
        meta["candidates_count"] = len(candidates)
        if not candidates:
            return [], total, meta

        if enrich_browser:
            # Browser-Use нужен там, где бесплатные источники не справились:
            # страница не прочиталась ИЛИ цена не нашлась. Раньше условие было
            # только про непрочитанные страницы, поэтому при 12 успешно
            # прочитанных каталогах без цены платный браузер не запускался
            # ни разу — а именно там, где он нужен.
            need_browser = [
                c
                for c in candidates[:page_fetch_top_n]
                if "Страницу поставщика не удалось прочитать" in c.warnings
                or "Сайт закрыт анти-ботом" in c.warnings
                or c.price_kzt is None
            ]
            if need_browser:
                costs = await self.enrich_with_browser(need_browser, top_n=3)
                total.merge(costs)
                meta["resolution_gaps"] = requirement_resolution_gaps(
                    requirements, candidates
                )

        if perform_matching:
            costs = await self.match_requirements(candidates, requirements)
            total.merge(costs)
            self.assess_budget(candidates, requirements, budget_kzt)

        candidates.sort(
            key=lambda c: (
                1 if c.budget_status == "over_budget" else 0,
                -c.score,
                {"kz": 0, "neutral": 1, "foreign": 2}.get(domain_country_hint(c.domain), 1),
                c.domain.lower(),
                c.url.lower(),
            )
        )
        return candidates, total, meta

    @staticmethod
    def assess_budget(
        candidates: list[SupplierCandidate],
        requirements: list[Requirement],
        budget_kzt: float | None,
    ) -> None:
        """Сопоставить цену позиции, количество и бюджет всего лота."""
        if not budget_kzt or budget_kzt <= 0:
            return
        for candidate in candidates:
            if candidate.price_kzt is None:
                continue
            relevant = [
                req
                for req in requirements
                if _tokens_overlap(candidate.title, req.title)
                or any(
                    m.get("code") == req.code
                    and m.get("status") in {MATCH_FITS, MATCH_PARTIAL}
                    for m in candidate.requirement_matches
                )
            ]
            quantities = [q for req in relevant if (q := extract_quantity(req))]
            quantity = max(quantities) if quantities else 1
            candidate.estimated_total_kzt = candidate.price_kzt * quantity
            if candidate.estimated_total_kzt > budget_kzt:
                candidate.budget_status = "over_budget"
                candidate.score = max(0, candidate.score - 30)
                candidate.warnings.append(
                    f"Расчётная стоимость {candidate.estimated_total_kzt:,.0f} ₸ "
                    f"превышает бюджет лота {budget_kzt:,.0f} ₸."
                )
            else:
                candidate.budget_status = "within_budget"

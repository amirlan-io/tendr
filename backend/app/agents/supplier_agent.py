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
from collections.abc import Iterable
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

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")
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
    """Накопитель расходов по шагам (пишется в аудит, F10)."""

    llm_usd: float = 0.0
    tavily_usd: float = 0.0
    browser_usd: float = 0.0
    # Счётчики бесплатных операций — для отчётности по себестоимости.
    page_fetch_count: int = 0

    def merge(self, other: "Costs") -> None:
        self.llm_usd += other.llm_usd
        self.tavily_usd += other.tavily_usd
        self.browser_usd += other.browser_usd
        self.page_fetch_count += other.page_fetch_count


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


def _tokens_overlap(query: str, title: str) -> bool:
    """Есть ли значимое пересечение слов между запросом и пунктом ТЗ."""
    def _tokens(text: str) -> set[str]:
        words = re.findall(r"[а-яёa-z]{4,}", (text or "").lower())
        return {w for w in words if w not in _STOP_WORDS}

    q, t = _tokens(query), _tokens(title)
    return bool(q & t)


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
    # Отсекаем мусор: email из картинки/метрики.
    if email and (email.endswith((".png", ".jpg", ".webp")) or len(email) > 64):
        email = ""
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
    async def build_queries(
        self, requirements: list[Requirement], *, budget_kzt: float | None = None
    ) -> tuple[list[str], Costs]:
        costs = Costs()
        if not requirements:
            return [], costs
        req_lines = "\n".join(
            f"- {r.title}" + (f" ({r.description[:200]})" if r.description else "")
            for r in requirements[:8]
        )
        prompt = (
            "Пункты ТЗ, по которым нужно найти поставщика:\n"
            f"{req_lines}\n\n"
            f"Бюджет: {budget_kzt if budget_kzt else 'не указан'} тг\n\n"
            "Составь 3–7 поисковых запросов: товар + синонимы + ключевые характеристики, "
            "на русском и казахском языках. Верни JSON {\"queries\": [...]}."
        )
        data = await self._chat_json(prompt, max_tokens=800)
        queries = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]
        # Стоимость считаем приблизительно по среднему тарифу flash-моделей.
        costs.llm_usd += 0.0002
        if not queries:
            # Fallback: заголовки требований как запросы.
            queries = [r.title for r in requirements[:3]]
        return queries[:7], costs

    # ── Шаг 2: Tavily ────────────────────────────────────────────────
    async def search_web(
        self,
        queries: list[str],
        *,
        max_results: int = 20,
        domains: Sequence[str] | None = DEFAULT_SEARCH_DOMAINS,
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
        for query in queries[:7]:
            try:
                kwargs: dict[str, Any] = dict(
                    query=query,
                    search_depth="advanced",
                    max_results=10,
                )
                if domains:
                    kwargs["include_domains"] = list(domains)
                response = self._tavily_client.search(**kwargs)
            except Exception as exc:
                logger.warning("[supplier] Tavily search failed for '{}': {}", query, exc)
                continue
            # ~$0.008 за запрос (средняя оценка по тарифам Tavily).
            costs.tavily_usd += 0.008
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
        self, requirements: list[Requirement], *, max_results: int = 12
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

        # Запросы строим из названия товара + подсказка «производитель/оптом».
        base_terms: list[str] = []
        for req in requirements[:3]:
            title = re.sub(r"[^\w\s-]", " ", req.title).strip()
            title = re.sub(r"\s+", " ", title)[:60]
            if title:
                base_terms.append(title)
        if not base_terms:
            return [], costs

        queries: list[str] = []
        for term in base_terms[:2]:
            queries.append(f"{term} {_MANUFACTURER_QUERY_SUFFIXES[0]}")
        queries.append(f"{base_terms[0]} {_MANUFACTURER_QUERY_SUFFIXES[1]}")
        queries = queries[:3]

        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for query in queries:
            try:
                # Без include_domains — ищем сайты компаний по всему вебу.
                response = self._tavily_client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=8,
                )
            except Exception as exc:
                logger.warning("[supplier] manufacturer search failed: {}", exc)
                continue
            costs.tavily_usd += 0.008  # ~$0.008 за запрос
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
        self, candidates: list[SupplierCandidate], *, top_n: int = 5
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
            page = await fetch_page(candidate.url)
            if not page.is_usable:
                logger.info(
                    "[supplier] страница не прочитана ({}): {}",
                    page.provider,
                    page.error or "empty",
                )
                candidate.warnings.append("Страницу поставщика не удалось прочитать.")
                continue
            costs.page_fetch_count += 1
            self._apply_page_text(candidate, page.text)
        return costs

    def _apply_page_text(self, candidate: SupplierCandidate, text: str) -> None:
        """Разобрать текст страницы: контакты, цена, наличие, город."""
        from app.agents.product_search import _parse_price

        email, phone = find_contacts(text)
        if email and not candidate.email:
            candidate.email = email
            candidate.sources["email"] = candidate.url
        if phone and not candidate.phone:
            candidate.phone = phone
            candidate.sources["phone"] = candidate.url

        if candidate.price_kzt is None:
            # Ищем цену рядом со словом «тг»/«₸», чтобы не взять первую
            # попавшуюся цифру (год выпуска, количество и т.п.).
            price = None
            for match in re.finditer(r"([\d][\d\s]{1,11})\s*(?:₸|тг|KZT)", text):
                parsed = _parse_price(match.group(1))
                if parsed and parsed > 0:
                    price = parsed
                    break
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
                "Верни JSON {\"requirement_matches\": [{\"code\": \"...\", "
                "\"title\": \"...\", \"status\": \"fits|partial|no|unknown\", "
                "\"comment\": \"...\", \"source_url\": \"...\"}]}."
                "Если данных нет — status=unknown, а не догадка."
            )
            data = await self._chat_json(prompt, max_tokens=1500)
            costs.llm_usd += 0.0005
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
                matches.append(
                    {
                        "code": known.code if known else code[:64],
                        "title": (known.title if known else title)[:512],
                        "status": normalize_match_status(raw.get("status")),
                        "comment": str(raw.get("comment") or "")[:1000],
                        "source_url": str(raw.get("source_url") or "")[:1000] or candidate.url,
                    }
                )
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
            candidate.warnings = build_warnings(candidate, requirements)

        return costs

    # ── Оркестрация ──────────────────────────────────────────────────
    async def run(
        self,
        requirements: list[Requirement],
        *,
        budget_kzt: float | None = None,
        blocked: set[str] | None = None,
        enrich_browser: bool = True,
        page_fetch_top_n: int = 5,
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
        page_fetch_top_n: int = 5,
    ) -> tuple[list[SupplierCandidate], Costs, dict[str, Any]]:
        """Полный конвейер F1+F2. Возвращает кандидатов, расходы и метаданные."""
        requirements = dedupe_requirements(requirements)
        total = Costs()
        meta: dict[str, Any] = {"queries": [], "candidates_count": 0, "blocked_filtered": 0}

        if not requirements:
            return [], total, meta

        queries, costs = await self.build_queries(requirements, budget_kzt=budget_kzt)
        total.merge(costs)
        meta["queries"] = queries
        if not queries:
            return [], total, meta

        # Лот часто мультипозиционный. Если искать по всем запросам разом,
        # позиционный товар «съедает» лимит: на живом прогоне лота
        # «фильтр + регулятор давления» все 20 мест ушли поставщикам
        # фильтров, и по регулятору не осталось никого.
        # Поэтому каждый пункт ТЗ получает свою квоту результатов.
        per_item_queries = self._queries_by_requirement(requirements, queries)
        results: list[dict[str, Any]] = []
        if len(per_item_queries) > 1:
            per_item_quota = max(3, 20 // len(per_item_queries))
            for item_queries in per_item_queries:
                found, costs = await self.search_web(item_queries, max_results=per_item_quota)
                total.merge(costs)
                results.extend(found)
            results = _dedupe_results(results)[:20]
        else:
            results, costs = await self.search_web(queries)
            total.merge(costs)

        # Вторая фаза: сайты производителей и дилеров в открытом вебе.
        manufacturer_results, costs = await self.search_manufacturers(requirements)
        total.merge(costs)
        known_urls = {str(item.get("url")) for item in results}
        for item in manufacturer_results:
            if item["url"] in known_urls:
                continue
            results.append(item)
            known_urls.add(item["url"])

        if not results:
            return [], total, meta

        blocked = blocked or set()
        candidates: list[SupplierCandidate] = []
        # Приоритет: прямой поставщик важнее витрины. Без этой сортировки
        # маркетплейсы забивают лимит 20 первыми, и сайты производителей
        # (а именно там есть контакты) до него не доходят.
        def _priority(item: dict[str, Any]) -> tuple[int, float]:
            domain = extract_domain(item["url"])
            kind = str(item.get("domain_kind") or classify_domain(domain))
            # 0 — прямой поставщик, 1 — агрегатор/неизвестно
            # Внутри группы приоритет казахстанским доменам: закупка в КЗ
            # без перекрёстной логистики и с местными документами.
            country_rank = {"kz": 0, "neutral": 1, "foreign": 2}.get(
                domain_country_hint(domain), 1
            )
            return (0 if kind == "direct" else 1, country_rank, -float(item.get("score") or 0.0))

        results = sorted(results, key=_priority)

        for item in results:
            domain = extract_domain(item["url"])
            supplier = item["title"][:256] or domain
            # Стоп-лист: не показываем и не предлагаем (F6).
            if supplier in blocked or domain in blocked:
                meta["blocked_filtered"] += 1
                continue
            kind = str(item.get("domain_kind") or classify_domain(domain))
            # Соцсети и доски объявлений пропускаем: контактов там нет.
            if kind == "classifieds":
                continue
            email, phone = find_contacts(item.get("content", ""))
            candidate = SupplierCandidate(
                supplier=supplier,
                domain=domain,
                title=item["title"][:512],
                url=item["url"],
                email=email,
                phone=phone,
                is_middleman=kind == "aggregator",
                domain_kind=kind,
            )
            candidate.sources["search"] = item["url"]
            candidates.append(candidate)
            if len(candidates) >= 20:  # критерий приёмки: ≤20 кандидатов
                break

        meta["candidates_count"] = len(candidates)
        if not candidates:
            return [], total, meta

        # Сначала бесплатное чтение страниц, потом (если нужно) платный браузер.
        if enrich_browser:
            costs = await self.enrich_with_pages(candidates, top_n=page_fetch_top_n)
            total.merge(costs)
            # Browser-Use нужен лишь там, где бесплатные источники не справились.
            if enrich_browser and any(
                "Страницу поставщика не удалось прочитать" in c.warnings
                for c in candidates[:page_fetch_top_n]
            ):
                costs = await self.enrich_with_browser(candidates, top_n=3)
                total.merge(costs)

        costs = await self.match_requirements(candidates, requirements)
        total.merge(costs)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates, total, meta
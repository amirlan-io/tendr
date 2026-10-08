"""ProductSearchAgent: поиск товаров и услуг в интернете по описанию из ТЗ.

Использует Tavily API — поисковик для AI-агентов.
Возвращает топ-N подходящих товаров с ценами, ссылками, рейтингами.
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

from app.agents.base import Agent
from app.core.config import get_settings
from app.schemas.lot import ProductItem, ProductSearchRequest, ProductSearchResult


def _s(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _parse_price(text: str) -> float | None:
    """Извлечь цену из строки. Понимает '45 990', '45 990 тг', '45990 KZT'."""
    if not text:
        return None
    # Убираем всё кроме цифр, пробелов и точек
    cleaned = re.sub(r"[^\d\s,.]", "", text)
    # Берём первое число
    m = re.search(r"\d[\d\s]*(?:\.\d+)?", cleaned)
    if not m:
        return None
    try:
        # Убираем пробелы (это разделители тысяч в KZ/RU)
        return float(m.group().replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _extract_domain(url: str) -> list[str]:
    """Вытащить домен из URL. Используется для allowed_domains в browser-use."""
    from urllib.parse import urlparse
    try:
        netloc = urlparse(url).netloc.lower()
        # Убираем www.
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return [netloc] if netloc else []
    except Exception:
        return []


def _build_browser_task(
        action: str,
        product: "ProductItem",
        request: "ProductSearchRequest") -> str:
    """Собрать промпт для browser-use на основе действия."""
    if action == "verify_price":
        return (
            f"Зайди на {product.url}. "
            f"Найди товар '{product.name}'. "
            f"Подтверди актуальную цену (тенге), наличие на складе. "
            f"Верни JSON: {{'price_kzt': 12345, 'in_stock': true/false, 'url': '...'}}"
        )
    if action == "extract_contacts":
        return (
            f"Зайди на {product.url}. "
            f"Найди раздел 'Контакты' или 'О компании'. "
            f"Собери: email, телефон, БИН/ИИН. "
            f"Верни JSON: {{'email': '...', 'phone': '...', 'bin': '...'}}"
        )
    if action == "book":
        # ВНИМАНИЕ: требует human-in-loop, НЕ делать автоматически
        return (
            f"Зайди на {product.url}. "
            f"Найди кнопку 'В корзину' или 'Заказать'. "
            f"Кликни на неё. "
            f"НЕ заполняй персональные данные и НЕ оплачивай. "
            f"Сделай скриншот состояния корзины. "
            f"Верни описание что произошло."
        )
    # fallback
    return f"Открой {product.url} и опиши что видишь."


class ProductSearchAgent(Agent):
    """Ищет товары/услуги в интернете по описанию потребности.

    Pipeline:
        1. AI генерирует 3-5 поисковых запросов на основе описания
        2. Tavily ищет на kaspi.kz, sulpak.kz, olx.kz, technodom.kz и др.
        3. AI фильтрует по критериям (цена, кол-во, наличие)
        4. Возвращает топ-5 с обоснованием соответствия
        5. (опционально) Browser-Use шаг для верификации цены / бронирования / контактов

        Без Tavily API (или с пустым ключом) — возвращает заглушку.
        """

    name = "product_search"

    system_prompt = """Ты — эксперт по закупкам в Казахстане. Твоя задача — помочь
заказчику или поставщику найти подходящие товары/услуги в казахстанских
интернет-магазинах (kaspi.kz, sulpak.kz, technodom.kz, olx.kz и т.д.).

Тебе будет дано:
- Описание потребности (что ищут)
- Бюджет, количество, характеристики
- Результаты поиска Tavily (до 10 ссылок с сниппетами)

Твоя задача:
1. Сгенерировать 3-5 разных поисковых запросов (на казахском и русском)
2. Проанализировать результаты поиска
3. Выбрать топ-5 наиболее подходящих товаров
4. Для каждого дать:
   - Название товара
   - Цену (тенге)
   - Ссылку
   - Магазин/продавец
   - Рейтинг (если есть)
   - Почему подходит
   - Возможные проблемы

Верни СТРОГО валидный JSON:
{
  "search_queries": ["запрос 1", "запрос 2", ...],
  "products": [
    {
      "name": "Название товара",
      "price_kzt": 45990,
      "url": "https://kaspi.kz/...",
      "store": "Kaspi.kz",
      "rating": 4.8,
      "reviews_count": 1234,
      "match_score": 95,
      "match_reason": "Соответствует требованиям ТЗ: ...",
      "concerns": ["Доставка 5-7 дней", ...]  // или []
    }
  ],
  "summary": "Общая сводка: найдено X товаров, Y соответствуют требованиям"
}
"""

    def __init__(self) -> None:
        self._tavily_client = None
        self._browser_agent = None
        settings = get_settings()
        tavily_key = getattr(settings, "tavily_api_key", None)
        if tavily_key:
            try:
                from tavily import TavilyClient

                self._tavily_client = TavilyClient(api_key=tavily_key)
            except Exception as e:
                logger.warning("Tavily init failed: {}", e)

        # === Опциональный Browser-Use агент ===
        browser_key = getattr(settings, "browser_use_api_key", None)
        if browser_key:
            try:
                from app.agents.browser_use import BrowserUseAgent
                self._browser_agent = BrowserUseAgent(api_key=browser_key)
                logger.info("[product_search] Browser-Use agent initialized")
            except Exception as e:
                logger.warning(
                    f"[product_search] Browser-Use init failed: {e}")

    async def run(
        self, request: ProductSearchRequest, *, lot_id: str = "search"
    ) -> ProductSearchResult:
        """Ищет товары по запросу.

        Args:
            request: описание потребности + критерии
            lot_id: для логирования
        """
        # Одинаковые правила доказательной сверки для поиска товаров и поставщиков.
        from app.agents.supplier_agent import (
            SupplierAgent, Requirement, has_mandatory_mismatch, has_supported_match,
        )
        description = request.additional_info or ""
        if request.quantity:
            description += f" Количество {request.quantity} шт."
        requirements = [Requirement("product", request.query, description, True)]
        agent = SupplierAgent()
        candidates, costs, meta = await agent.find_suppliers(
            requirements, budget_kzt=request.budget_kzt, enrich_browser=True,
            page_fetch_top_n=5, allow_browser_fallback=False,
        )
        usable = [c for c in candidates if has_supported_match(c, requirements)
                  and not has_mandatory_mismatch(c, requirements)
                  and c.budget_status != "over_budget"]
        products = [ProductItem(
            name=c.title, price_kzt=c.price_kzt, url=c.url, store=c.supplier,
            match_score=c.score,
            match_reason=" ".join(m.get("comment", "") for m in c.requirement_matches)[:500],
            concerns=list(c.warnings),
        ) for c in usable[:5]]
        queries = meta.get("queries", [])
        summary = (
            f"Найдено {len(products)} кандидатов с подтверждёнными данными; "
            f"полностью соответствуют ТЗ: {sum(c.score == 100 for c in usable[:5])}. "
            "Неизвестные характеристики, наличие и доставка требуют уточнения."
        )
        if not agent._tavily_client:
            summary = "Tavily API не сконфигурирован. Добавьте TAVILY_API_KEY в .env"

        # === ШАГ 4 (опционально): Browser-Use ===
        # Если в запросе указан browser_action — запускаем браузер для top-N
        # результатов
        browser_actions_count = 0
        browser_total_cost = 0.0
        browser_total_duration = 0.0
        browser_session = getattr(self, "_browser_agent", None)
        browser_available = browser_session is not None

        if request.browser_action and products and browser_available:
            try:
                top_n = products[:3]  # Не больше 3 чтобы не разориться
                for prod in top_n:
                    if not prod.url:
                        continue
                    logger.info(
                        f"[product_search] browser_action='{request.browser_action}' for {prod.url}"
                    )
                    result = await browser_session.run_task(
                        task=_build_browser_task(request.browser_action, prod, request),
                        model=request.browser_model or "gpt-5.4-mini",
                        proxy_country="kz",
                        allowed_domains=_extract_domain(prod.url),
                        enable_recording=True,
                        max_duration_min=5,
                    )
                    browser_actions_count += 1
                    try:
                        browser_total_cost += float(getattr(result,
                                                    "cost_usd", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        pass
                    browser_total_duration += float(
                        getattr(result, "duration_sec", 0.0) or 0.0)

                    # Применяем результат к продукту
                    output = getattr(result, "output", None)
                    if request.browser_action == "verify_price" and isinstance(
                            output, dict):
                        verified = output.get(
                            "price_kzt") or output.get("price")
                        if verified:
                            try:
                                prod.browser_verified_price = float(
                                    str(verified).replace(" ", "").replace("₸", "")
                                )
                            except (TypeError, ValueError):
                                pass
                            from datetime import datetime, timezone
                            prod.browser_verified_at = datetime.now(
                                timezone.utc).isoformat()
                        # дописываем в concerns
                        if output.get("email"):
                            prod.concerns.append(f"📧 Email: {output['email']}")
                        if output.get("phone"):
                            prod.concerns.append(f"📞 Тел: {output['phone']}")

                    prod.browser_session_id = getattr(
                        result, "session_id", None)
                    # recording_url не входит в схему ProductItem — сохраняем в concerns,
                    # чтобы не терять информацию.
                    rec_url = getattr(result, "recording_url", None)
                    if rec_url:
                        prod.concerns = (prod.concerns or []) + [f"🎬 Запись: {rec_url}"]

            except Exception as e:
                logger.warning(f"[product_search] browser_action failed: {e}")
                if not summary:
                    summary = ""
                summary += f"\n\n⚠️ Browser-Use шаг не выполнен: {e}"

        return ProductSearchResult(
            lot_id=lot_id,
            query=request.query,
            products=products,
            search_queries=queries,
            summary=summary,
            browser_actions_count=browser_actions_count,
            browser_total_cost_usd=browser_total_cost,
            browser_total_duration_sec=browser_total_duration,
        )



    async def run_deep(
        self,
        request: "DeepSearchRequest",  # type: ignore
        session=None,
        *,
        lot_id: str = "deep_search",
    ):
        """Глубокий поиск с извлечением характеристик и историческим анализом.

        Pipeline:
        1. Извлечь технические характеристики из текста ТЗ
        2. Сгенерировать поисковые запросы на основе характеристик
        3. Найти товары через Tavily (Kaspi, Sulpak, OLX...)
        4. Отфильтровать по совместимости с характеристиками
        5. Сравнить с историей цен (наша БД)
        """
        from app.schemas.lot import (
            DeepSearchResult,
            PriceComparison,
            ProductItem,
        )
        from app.services.price_analyzer import get_price_stats
        from app.services.spec_extractor import SpecExtractor

        # 1. Извлечь характеристики из ТЗ
        spec_extractor = SpecExtractor()
        specs = await spec_extractor.extract(request.lot_text)
        product_name = specs.get("product_name", "товар")
        keywords = specs.get("search_keywords", [])
        key_specs = specs.get("key_specs", {})

        # 2. Сгенерировать поисковые запросы
        queries = list(keywords) if keywords else [product_name]
        # Добавляем бюджет-ориентированный запрос
        if request.budget_kzt and request.quantity:
            per_unit = request.budget_kzt / max(request.quantity, 1)
            queries.append(f"{product_name} до {per_unit:,.0f} тенге")
        if not queries:
            queries = [product_name]

        # 3. Ищем через Tavily
        all_results = []
        if self._tavily_client:
            for q in queries[:6]:  # до 6 разных поисковых запросов
                try:
                    response = self._tavily_client.search(
                        query=q,
                        search_depth="advanced",
                        max_results=15,  # до 15 результатов на запрос
                        include_domains=[
                            # Крупные маркетплейсы и магазины KZ
                            "kaspi.kz",
                            "sulpak.kz",
                            "technodom.kz",
                            "olx.kz",
                            "shop.kz",
                            "mechta.kz",
                            "whitewind.kz",
                            "bifi.kz",
                            "flip.kz",
                            "marwin.kz",
                            "lamoda.kz",
                            # Производители и поставщики KZ
                            "omniparts.kz",
                            "vernal.kz",
                            "klimatech.kz",
                            "filter.kz",
                            # Российские маркетплейсы (KZ доставляют)
                            "wildberries.kz",
                            "wildberries.ru",
                            "ozon.kz",
                            "ozon.ru",
                        ],
                    )
                    for r in response.get("results", []):
                        all_results.append(
                            {
                                "title": r.get("title", ""),
                                "url": r.get("url", ""),
                                "content": r.get("content", ""),
                                "score": r.get("score", 0),
                            }
                        )
                except Exception as e:
                    logger.warning("Tavily search failed: {}", e)

        # Убираем дубликаты по URL
        seen = set()
        unique = []
        for r in all_results:
            u = r.get("url", "")
            if u and u not in seen:
                seen.add(u)
                unique.append(r)

        # 4. AI фильтрует с учётом характеристик из specs
        products: list = []
        filtered: dict | None = None
        if unique:
            results_text = "\n\n".join(
                f"[{i + 1}] {r['title']}\nURL: {r['url']}\n{r['content'][:300]}"
                for i, r in enumerate(unique[:10])
            )
            filter_prompt = (
                f"Товар: {product_name}\n"
                f"Характеристики из ТЗ: {key_specs}\n"
                f"Бюджет: {request.budget_kzt or '—'} тг\n"
                f"Количество: {request.quantity or '—'}\n"
                f"Исключить: {specs.get('search_exclude', [])}\n\n"
                f"Результаты поиска ({len(unique)} шт):\n{results_text}\n\n"
                "Выбери топ-5 наиболее подходящих. Учти характеристики и бюджет. Верни JSON."
            )
            filtered = await self._chat_json(filter_prompt, max_tokens=6000)
            if filtered and isinstance(filtered, dict):
                for p in filtered.get("products", []):
                    if not isinstance(p, dict):
                        continue
                    price = p.get("price_kzt")
                    if price is None and p.get("price_text"):
                        price = _parse_price(str(p["price_text"]))
                    if price is None and p.get("price"):
                        price = _parse_price(str(p["price"]))
                    products.append(
                        ProductItem(
                            name=_s(p.get("name"))[:200],
                            price_kzt=price,
                            price_text=_s(p.get("price_text") or p.get("price"))[:100],
                            url=_s(p.get("url"))[:500],
                            store=_s(p.get("store"))[:100],
                            rating=p.get("rating")
                                if isinstance(p.get("rating"), (int, float))
                                else None,
                            reviews_count=p.get("reviews_count")
                                if isinstance(p.get("reviews_count"), int)
                                else None,
                            match_score=int(p.get("match_score", 0))
                                if isinstance(p.get("match_score"), (int, float))
                                else 0,
                            match_reason=_s(p.get("match_reason"))[:500],
                            concerns=p.get("concerns") or [],
                        )
                    )

        # 5. Историческое сравнение цен
        price_comp = PriceComparison()
        if session is not None:
            try:
                stats = await get_price_stats(session, product_name, limit=50)
                price_comp = PriceComparison(
                    count=stats.count,
                    avg_price=stats.avg_price,
                    min_price=stats.min_price,
                    max_price=stats.max_price,
                    median_price=stats.median_price,
                    similar_lots=stats.sources,
                    recommendation=stats.recommendation,
                )
            except Exception as e:
                logger.warning("Price stats failed: {}", e)

        # Сравниваем найденные товары с историей
        prices_found = [p.price_kzt for p in products if p.price_kzt]
        if prices_found and price_comp.median_price:
            for p in products:
                if p.price_kzt and p.price_kzt > price_comp.median_price * 1.2:
                    p.concerns = (p.concerns or []) + [
                        f"Цена на 20%+ выше медианы по рынку ({price_comp.median_price:,.0f} ₸)"
                    ]

        # Формируем summary — вне зависимости от того, нашли ли цены.
        if filtered and isinstance(filtered, dict) and filtered.get("summary"):
            summary = _s(filtered.get("summary"))
        else:
            summary = f"Найдено {len(products)} товаров по запросу «{product_name}»."
            if price_comp.median_price:
                summary += f" Средняя цена по рынку: {price_comp.median_price:,.0f} ₸."

        return DeepSearchResult(
            extracted_specs=key_specs,
            product_name=product_name,
            category=specs.get("category", ""),
            search_queries=queries,
            products=products,
            price_comparison=price_comp,
            summary=summary,
            total_found=len(unique),
        )

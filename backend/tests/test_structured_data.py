"""Тесты извлечения структурированных данных о товарах из HTML.

Фикстуры повторяют реальную вёрстку, на которой модуль ломается:
- ankas.kz — цена в ``<meta itemprop="price">`` внутри Offer-scope, при этом
  в видимом тексте нет слов «тг»/«₸»;
- pnevmoteh.kz — вложенный Brand-scope с мусорным именем «-» и дубль цены;
- цена 0 на ankas означает «Уточнить цену» и не должна становиться ценой 0.
"""

from __future__ import annotations

from app.agents.structured_data import (
    ProductRecord,
    extract_products,
    normalize_price,
    pick_price,
)


def _page(body: str, head: str = "") -> str:
    return f"<html><head>{head}</head><body>{body}</body></html>"


# ---------------------------------------------------------------------------
# normalize_price
# ---------------------------------------------------------------------------
def test_normalize_price_formats():
    assert normalize_price("107000") == 107000
    assert normalize_price("107 000") == 107000
    assert normalize_price("107 000,00") == 107000
    assert normalize_price("₸107 000") == 107000
    assert normalize_price("107,000.00") == 107000
    assert normalize_price("KZT 107000") == 107000
    assert normalize_price("1 176 000") == 1176000


def test_normalize_price_garbage_returns_none():
    assert normalize_price(None) is None
    assert normalize_price("") is None
    assert normalize_price("abc") is None
    assert normalize_price("по запросу") is None
    assert normalize_price("уточнить цену") is None


def test_normalize_price_foreign_currency_is_not_kzt():
    """Доллары/евро/рубли нельзя выдавать за тенге — это исказило бы расчёт."""
    assert normalize_price("$1,234.56") is None
    assert normalize_price("100 USD") is None
    assert normalize_price("5000 руб") is None
    assert normalize_price("99 EUR") is None
    assert normalize_price("€45") is None


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------
def test_json_ld_product_with_offer():
    html = _page(
        "",
        head="""
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Регулятор давления Madas",
          "offers": {
            "@type": "Offer",
            "price": "446000",
            "priceCurrency": "KZT",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        """,
    )
    records = extract_products(html)
    assert len(records) == 1
    record = records[0]
    assert record.name == "Регулятор давления Madas"
    assert record.price_kzt == 446000
    assert record.currency == "KZT"
    assert record.in_stock is True
    assert record.source == "json_ld"


def test_json_ld_graph_with_aggregate_offer():
    """@graph + AggregateOffer: берём lowPrice как актуальную цену «от»."""
    html = _page(
        "",
        head="""
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {"@type": "Organization", "name": "ООО Ромашка"},
            {
              "@type": "Product",
              "name": "Фильтр топливный",
              "offers": {
                "@type": "AggregateOffer",
                "lowPrice": "107000",
                "highPrice": "150000",
                "priceCurrency": "KZT",
                "availability": "http://schema.org/InStock"
              }
            }
          ]
        }
        </script>
        """,
    )
    records = extract_products(html)
    assert [r.price_kzt for r in records] == [107000]
    assert records[0].source == "json_ld"


def test_json_ld_price_specification_and_list_offers():
    html = _page(
        "",
        head="""
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Компрессор ABAC",
          "offers": [
            {"@type": "Offer", "priceSpecification": {"price": "273000", "priceCurrency": "KZT"}}
          ]
        }
        </script>
        """,
    )
    assert [r.price_kzt for r in extract_products(html)] == [273000]


def test_json_ld_out_of_stock():
    html = _page(
        "",
        head="""
        <script type="application/ld+json">
        {"@type": "Product", "name": "Товар",
         "offers": {"@type": "Offer", "price": "1000",
                    "availability": "http://schema.org/OutOfStock"}}
        </script>
        """,
    )
    assert extract_products(html)[0].in_stock is False


def test_json_ld_foreign_currency_not_kzt():
    """priceCurrency лежит отдельным полем — USD не должен стать ценой в тенге."""
    html = _page(
        "",
        head="""
        <script type="application/ld+json">
        {"@type": "Product", "name": "Import valve",
         "offers": {"@type": "Offer", "price": "49.99", "priceCurrency": "USD"}}
        </script>
        """,
    )
    assert extract_products(html) == []


def test_json_ld_broken_json_does_not_raise():
    """Битый JSON-LD не должен ронять разбор — вернётся пусто или частичный итог."""
    html = _page(
        "",
        head='<script type="application/ld+json">{"@type": "Product", "name": </script>',
    )
    assert extract_products(html) == []


def test_json_ld_recursive_graph_terminates():
    """Глубокая вложенность ограничена, рекурсия не уходит в бесконечность."""
    deep: dict = {"@type": "Product", "name": "Глубокий", "offers": {"@type": "Offer", "price": "500"}}
    node: dict = deep
    for _ in range(500):
        node = {"@type": "WebPage", "mainEntity": node}
    import json

    html = _page("", head=f'<script type="application/ld+json">{json.dumps(node)}</script>')
    assert extract_products(html) == []  # слишком глубоко — честно не нашли


# ---------------------------------------------------------------------------
# Microdata (реальная вёрстка ankas.kz)
# ---------------------------------------------------------------------------
ANKAS_CARD = """
<div itemscope itemtype="https://schema.org/Product">
  <a href="/p"><span>Фильтр для топлива и масла Piusi 60 л/мин</span>
    <meta itemprop="name" content="Фильтр для топлива и масла Piusi 60 л/мин"></a>
  <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
    <meta itemprop="price" content="{price}">
    <meta itemprop="priceCurrency" content="KZT">
    <link itemprop="availability" href="http://schema.org/InStock"/>
  </div>
</div>
"""


def test_microdata_matches_ankas_layout():
    html = _page(ANKAS_CARD.format(price="33000"))
    records = extract_products(html)
    assert len(records) == 1
    record = records[0]
    assert record.price_kzt == 33000
    assert record.currency == "KZT"
    assert record.in_stock is True
    assert record.source == "microdata"
    assert record.name.startswith("Фильтр для топлива")


def test_microdata_multiple_products_keep_document_order():
    """Порядок в HTML важен: pick_price берёт первое совпадение."""
    html = _page(
        ANKAS_CARD.format(price="33000") + ANKAS_CARD.format(price="69500")
    )
    records = extract_products(html)
    assert [r.price_kzt for r in records] == [33000, 69500]


def test_microdata_nested_brand_does_not_become_product_name():
    """Вложенный Brand-scope с именем «-» не должен перебивать название товара."""
    html = _page(
        """
        <div itemscope itemtype="https://schema.org/Product">
          <div itemprop="brand" itemscope itemtype="https://schema.org/Brand">
            <meta itemprop="name" content="-">
          </div>
          <meta itemprop="name" content="Пороховой монтажный пистолет ПЦ-84">
          <div itemprop="offers" itemscope itemtype="http://schema.org/Offer">
            <meta itemprop="price" content="195994">
            <meta itemprop="priceCurrency" content="KZT">
          </div>
        </div>
        """
    )
    assert extract_products(html)[0].name == "Пороховой монтажный пистолет ПЦ-84"


def test_microdata_duplicated_price_not_duplicated_record():
    """Мобильная и десктопная вёрстка дублируют цену — товар должен быть один."""
    html = _page(
        """
        <div itemscope itemtype="https://schema.org/Product">
          <meta itemprop="name" content="Компрессор ABAC A29B">
          <div itemprop="offers" itemscope itemtype="http://schema.org/Offer">
            <meta itemprop="price" content="273000">
          </div>
          <div class="mobile">
            <div itemprop="offers" itemscope itemtype="http://schema.org/Offer">
              <meta itemprop="price" content="273000">
            </div>
          </div>
        </div>
        """
    )
    records = extract_products(html)
    assert len(records) == 1
    assert records[0].price_kzt == 273000


def test_microdata_zero_price_means_request_price():
    """«Уточнить цену» размечено как price=0 — это отсутствие цены, а не 0 тенге."""
    html = _page(
        """
        <div itemscope itemtype="https://schema.org/Product">
          <meta itemprop="name" content="Фильтр бензина Separ">
          <span>Уточнить цену</span>
          <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
            <meta itemprop="price" content="0">
          </div>
        </div>
        """
    )
    record = extract_products(html)[0]
    assert record.price_kzt is None
    assert record.raw_price == "0"


def test_microdata_without_price_gives_none():
    """Нет цены — возвращаем None, а не выдумываем число."""
    html = _page(
        """
        <div itemscope itemtype="https://schema.org/Product">
          <meta itemprop="name" content="Регулятор GDJ">
        </div>
        """
    )
    record = extract_products(html)[0]
    assert record.price_kzt is None


# ---------------------------------------------------------------------------
# OpenGraph
# ---------------------------------------------------------------------------
def test_opengraph_price():
    html = _page(
        "",
        head="""
        <meta property="og:title" content="Клапан Ду 15">
        <meta property="og:price:amount" content="15 500">
        <meta property="og:price:currency" content="KZT">
        <meta property="product:availability" content="in stock">
        """,
    )
    record = extract_products(html)[0]
    assert record.source == "opengraph"
    assert record.price_kzt == 15500
    assert record.name == "Клапан Ду 15"
    assert record.in_stock is True


def test_product_price_amount_property():
    html = _page(
        "",
        head="""
        <meta property="product:name" content="Фильтр FBO">
        <meta property="product:price:amount" content="1176000">
        <meta property="product:price:currency" content="KZT">
        """,
    )
    assert extract_products(html)[0].price_kzt == 1176000


def test_opengraph_foreign_currency_not_kzt():
    html = _page(
        "",
        head="""
        <meta property="og:title" content="Import part">
        <meta property="og:price:amount" content="49.99">
        <meta property="og:price:currency" content="USD">
        """,
    )
    assert extract_products(html) == []


# ---------------------------------------------------------------------------
# Таблицы
# ---------------------------------------------------------------------------
def test_table_with_header():
    html = _page(
        """
        <table>
          <tr><th>Наименование</th><th>Цена, тг</th></tr>
          <tr><td>Регулятор Madas FRG/2MC DN 50</td><td>446 000</td></tr>
          <tr><td>Регулятор Elco FGDR20</td><td>72 000</td></tr>
        </table>
        """
    )
    records = extract_products(html)
    assert [r.price_kzt for r in records] == [446000, 72000]
    assert records[0].source == "table"
    assert records[0].name == "Регулятор Madas FRG/2MC DN 50"


def test_table_without_header_requires_currency():
    html = _page(
        """
        <table>
          <tr><td>33 000 ₸</td><td>Фильтр для топлива</td></tr>
        </table>
        """
    )
    records = extract_products(html)
    assert records[0].price_kzt == 33000
    assert records[0].name == "Фильтр для топлива"


def test_table_row_without_numbers_skipped():
    html = _page(
        """
        <table>
          <tr><td>Итого</td><td>нет данных</td></tr>
          <tr><td>12 000 ₸</td><td>Товар</td></tr>
        </table>
        """
    )
    assert [r.price_kzt for r in extract_products(html)] == [12000]


# ---------------------------------------------------------------------------
# pick_price
# ---------------------------------------------------------------------------
def _record(name: str, price: float | None, order: int = 0) -> ProductRecord:
    return ProductRecord(
        name=name,
        price_kzt=price,
        currency="KZT" if price else None,
        in_stock=None,
        source="microdata",
        raw_price=str(price or ""),
    )


def test_pick_price_matches_case_insensitively():
    products = [_record("Фильтр для ТОПЛИВА Piusi", 33000)]
    assert pick_price(products, "фильтр для топлива") == 33000


def test_pick_price_returns_first_match_not_first_price_on_page():
    """Ключевой антипаттерн: нельзя приписать «первую цену со страницы»."""
    products = [
        _record("Регулятор давления газа Elco FGDR50", 319000),
        _record("Регулятор давления газа Elco FGDR25", 72000),
    ]
    assert pick_price(products, "FGDR25") == 72000


def test_pick_price_matches_by_all_words():
    products = [_record("Регулятор давления газа Madas FRG/2MC DN 50", 446000)]
    assert pick_price(products, "Madas DN 50") == 446000


def test_pick_price_ignores_yo_and_punctuation():
    products = [_record("Фильтр дизельного топлива", 15800)]
    assert pick_price(products, "дизельного топлива") == 15800
    assert pick_price(products, "Фильтр, дизельного!") == 15800


def test_pick_price_no_match_returns_none():
    products = [_record("Регулятор давления газа Madas", 446000)]
    assert pick_price(products, "компрессор") is None
    assert pick_price([], "любой") is None
    assert pick_price(products, "") is None
    assert pick_price(products, "   ") is None


def test_pick_price_skips_matching_record_without_price():
    """Первое совпадение без цены не должно блокировать следующее с ценой."""
    products = [
        _record("Фильтр Separ 2000", None),
        _record("Фильтр Separ SWK", 34500),
    ]
    assert pick_price(products, "фильтр") == 34500


def test_pick_price_all_matches_without_price_returns_none():
    products = [_record("Регулятор GDJ", None)]
    assert pick_price(products, "GDJ") is None


# ---------------------------------------------------------------------------
# Устойчивость
# ---------------------------------------------------------------------------
def test_empty_and_none_inputs():
    assert extract_products("") == []
    assert extract_products(None) == []
    assert extract_products("не html вовсе") == []


def test_truncated_html_does_not_raise():
    html = _page(ANKAS_CARD.format(price="33000"))
    assert extract_products(html[: len(html) // 2]) is not None


def test_unicode_mojibake_does_not_raise():
    html = "<html><body><meta itemprop='price' content='33000'></body></html>"
    assert extract_products(html.encode("utf-8", "replace").decode("latin-1")) is not None


def test_large_html_is_handled_quickly():
    import time

    filler = "<div>lorem ipsum dolor sit amet</div>"
    html = _page(filler * 40_000 + ANKAS_CARD.format(price="33000"))
    start = time.time()
    records = extract_products(html)
    assert time.time() - start < 5
    assert any(r.price_kzt == 33000 for r in records)


# ---------------------------------------------------------------------------
# Запасной путь без lxml (регулярки)
# ---------------------------------------------------------------------------
def test_regex_fallback_json_ld_and_opengraph(monkeypatch):
    """Без lxml модуль не падает и разбирает плоские источники (JSON-LD, OG)."""
    import builtins

    import app.agents.structured_data as module

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "lxml" or name.startswith("lxml."):
            raise ImportError("lxml недоступен")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(module, "_HAS_LXML", False)
    monkeypatch.setattr(module, "_extract_all", module._extract_via_regex)

    json_ld = _page(
        "",
        head='<script type="application/ld+json">'
        '{"@type":"Product","name":"Фильтр Piusi",'
        '"offers":{"@type":"Offer","price":"33000","priceCurrency":"KZT"}}'
        "</script>",
    )
    records = extract_products(json_ld)
    assert [(r.name, r.price_kzt, r.source) for r in records] == [("Фильтр Piusi", 33000, "json_ld")]

    og = _page(
        "",
        head='<meta property="og:price:amount" content="15 500">'
        '<meta property="og:title" content="Клапан Ду 15">',
    )
    assert [(r.name, r.price_kzt) for r in extract_products(og)] == [("Клапан Ду 15", 15500)]


def test_regex_fallback_rejects_foreign_currency(monkeypatch):
    """USD в og:price:currency не должен превратиться в цену в тенге."""
    import builtins

    import app.agents.structured_data as module

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "lxml" or name.startswith("lxml."):
            raise ImportError("lxml недоступен")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(module, "_HAS_LXML", False)
    monkeypatch.setattr(module, "_extract_all", module._extract_via_regex)

    html = _page(
        "",
        head='<meta property="og:price:amount" content="49.99">'
        '<meta property="og:price:currency" content="USD">',
    )
    assert extract_products(html) == []
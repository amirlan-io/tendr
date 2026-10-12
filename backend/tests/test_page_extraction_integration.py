"""Регрессии после интеграции: анти-бот заглушки и микроразметка цен.

Каждый тест воспроизводит реальную находку на живых сайтах.
"""

from __future__ import annotations

import pytest

from app.agents.page_guard import block_reason, looks_like_block_page, page_quality_score
from app.agents.structured_data import extract_products, pick_price

# Реальный ответ Jina на заблокированный zakazauto.kz
CAPTCHA_PAGE = """Title: Security Check

URL Source: https://zakazauto.kz/catalogs/filtry-toplivnye.html

Warning: This page maybe requiring CAPTCHA, please make sure you are authorized.

Markdown Content:

We have noticed some unusual activity and want to make sure everything is okay.

Enter the code from the image

![Image 1](https://zakazauto.kz/captcha_image/AmHAsWWXifGSXARteWDP.png)"""

# Реальный фрагмент каталога ankas.kz с ценами
REAL_CATALOG = """
# Регуляторы давления газа

Регулятор давления газа Madas FRG/2MC DN 15
Цена: 446 000 тенге
В наличии на складе в Алматы
+7 727 312 26 99

Регулятор давления газа Elco FGDR20
Цена: 72 000 тенге
info@ankas.kz
"""

# Реальная микроразметка: цена указана в itemprop, в тексте рядом нет валюты
ANKAS_HTML = """
<html><body>
<div itemscope itemtype="http://schema.org/Product">
  <h2 itemprop="name">Топливный фильтр Piusi Clear Captor Filter</h2>
  <meta itemprop="price" content="107000" />
  <meta itemprop="priceCurrency" content="KZT" />
  <link itemprop="availability" href="http://schema.org/InStock" />
</div>
<div itemscope itemtype="http://schema.org/Product">
  <h2 itemprop="name">Регулятор давления газа Madas FRG/2MC DN 15</h2>
  <meta itemprop="price" content="446000" />
  <meta itemprop="priceCurrency" content="KZT" />
</div>
</body></html>
"""

# Реальная микроразметка pnm-parts.ru: цена в рублях
RUB_HTML = """
<html><body>
<div itemscope itemtype="http://schema.org/Product">
  <h2 itemprop="name">PUROLATOR F 54423 - Фильтр топливный</h2>
  <meta itemprop="price" content="492.88" />
  <meta itemprop="priceCurrency" content="RUB" />
</div>
</body></html>
"""


# ───── Детектор заглушек ─────


def test_captcha_is_blocked_not_content() -> None:
    """Главная причина нулевых цен: капча считалась прочитанной страницей."""
    assert looks_like_block_page(CAPTCHA_PAGE) is True
    assert block_reason(CAPTCHA_PAGE) in {"captcha", "bot_check"}


def test_real_catalog_is_not_blocked() -> None:
    assert looks_like_block_page(REAL_CATALOG) is False
    assert block_reason(REAL_CATALOG) == ""
    assert page_quality_score(REAL_CATALOG) > 0


def test_page_quality_zero_means_placeholder() -> None:
    assert page_quality_score(CAPTCHA_PAGE) == 0


# ───── Микроразметка ─────


def test_price_from_microdata_without_currency_in_text() -> None:
    """На ankas.kz в тексте рядом с ценой нет слова «тенге».

    Цена живёт только в itemprop="price" — парсинг видимого текста её
    не находил, и поставщик оставался без цены.
    """
    products = extract_products(ANKAS_HTML)
    assert products
    assert pick_price(products, "Топливный фильтр") == 107_000.0
    assert pick_price(products, "Регулятор давления") == 446_000.0


def test_foreign_currency_is_never_returned_as_kzt() -> None:
    """Реальная находка: pnm-parts.ru отдаёт цену в рублях.

    Без фильтра 492.88 рубля выдавалось поставщику как 492.88 тенге —
    прямое искажение цены.
    """
    products = extract_products(RUB_HTML)
    assert pick_price(products, "Фильтр топливный") is None
    assert all(p.price_kzt is None or p.currency != "RUB" for p in products)


def test_pick_price_returns_none_when_no_match() -> None:
    """Нет товара — нет цены. Первая цена со страницы не годится."""
    products = extract_products(ANKAS_HTML)
    assert pick_price(products, "Ковёр для офиса") is None
    assert pick_price([], "любой") is None
    assert pick_price(products, "") is None


def test_missing_price_is_not_invented() -> None:
    html = """
    <html><body><div itemscope itemtype="http://schema.org/Product">
      <h2 itemprop="name">Топливный фильтр</h2>
      <span>Цена по запросу</span>
    </div></body></html>
    """
    products = extract_products(html)
    assert pick_price(products, "Топливный фильтр") is None
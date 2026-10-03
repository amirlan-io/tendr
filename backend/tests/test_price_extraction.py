"""Тесты извлечения цены рядом с названием товара.

Правило: цена берётся только рядом с названием товара. На каталоге из
десяти позиций первая цена на странице принадлежит другому товару, и
агент раньше приписывал поставщику чужое значение («123 ₸» за фильтр).
Лучше честное «нет данных», чем неверная цена в шорт-листе.
"""

from __future__ import annotations

from app.agents.supplier_agent import SupplierAgent, SupplierCandidate

CATALOG = """# Фильтры автомобильные
## Фильтр гидравлический SH56760
Цена: 5 000 тг
В наличии

## Фильтр топливный LYNXauto LF-876M
Цена: 22 560 тг

## Фильтр воздушный Atlas copco
Цена: 123 тг
"""


def _candidate(title: str) -> SupplierCandidate:
    return SupplierCandidate(
        supplier="ООО Тест", domain="flagma.kz", title=title, url="https://flagma.kz/p"
    )


def test_price_taken_from_own_card() -> None:
    agent = SupplierAgent()
    candidate = _candidate("Фильтр гидравлический SH56760")
    agent._apply_page_text(candidate, CATALOG)
    assert candidate.price_kzt == 5000.0


def test_price_of_another_product_is_not_borrowed() -> None:
    """Название есть, но рядом только чужие цены — лучше не знать."""
    agent = SupplierAgent()
    candidate = _candidate("Регулятор давления газа 21ч10п")
    agent._apply_page_text(candidate, CATALOG)
    assert candidate.price_kzt is None


def test_no_title_no_guessed_price() -> None:
    agent = SupplierAgent()
    candidate = _candidate("Абсолютно другой товар")
    agent._apply_page_text(candidate, CATALOG)
    assert candidate.price_kzt is None


def test_largest_price_in_card_window_wins() -> None:
    text = """## Фильтр масляный
Цена: 1 200 тг
Цена со скидкой: 950 тг
Старая цена: 3 400 тг
"""
    agent = SupplierAgent()
    candidate = _candidate("Фильтр масляный")
    agent._apply_page_text(candidate, text)
    assert candidate.price_kzt == 3400.0


def test_contacts_city_and_stock_still_extracted() -> None:
    text = (
        "## Фильтр гидравлический\n"
        "Пишите sales@example.kz, тел 7801-31090-30\n"
        "В наличии. Павлодар. Цена: 5 000 тг\n"
    )
    agent = SupplierAgent()
    candidate = _candidate("Фильтр гидравлический")
    agent._apply_page_text(candidate, text)
    assert candidate.email == "sales@example.kz"
    assert candidate.phone
    assert candidate.city == "Павлодар"
    assert candidate.in_stock is True
    assert candidate.price_kzt == 5000.0


def test_catalog_page_does_not_overwrite_existing_price() -> None:
    """Уже найденная цена не затирается данными каталога."""
    agent = SupplierAgent()
    candidate = _candidate("Фильтр гидравлический SH56760")
    candidate.price_kzt = 7777.0
    agent._apply_page_text(candidate, CATALOG)
    assert candidate.price_kzt == 7777.0

"""Тесты улучшений агента поставщиков (по итогам прогона на лоте 17726443).

Каждый тест закрывает конкретную находку живого прогона: нулевые цены,
неработающую персонализацию и неохват технических характеристик.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.supplier_agent import (
    Costs,
    Requirement,
    SupplierAgent,
    _manufacturer_queries,
    extract_search_term,
    extract_tech_hints,
    requirement_text,
)
from app.api.sandbox import _apply_filters, _budget_from_analysis


# ───── 1. Номенклатурное ядро вместо всей строки ТЗ ─────


@pytest.mark.parametrize(
    ("tz_text", "expected"),
    [
        ("Топливный фильтр для ДВС с непосредственным впрыском, легковой авто — 10 шт.", "Топливный фильтр"),
        ("Регулятор давления стальной, фланцевый, проход 80 мм, 60,3 Мпа — 1 шт.", "Регулятор давления стальной"),
        ("Стол офисный регулируемый, 1400х700", "Стол офисный регулируемый"),
        ("Компьютер офисный", "Компьютер офисный"),
    ],
)
def test_extract_search_term_drops_noise(tz_text: str, expected: str) -> None:
    """Предлоги и характеристики в поиске только мешают."""
    assert extract_search_term(tz_text) == expected


def test_extract_search_term_handles_empty() -> None:
    assert extract_search_term("") == ""
    assert extract_search_term(",,, ") == ""


def test_extract_tech_hints_picks_technical_markers() -> None:
    hints = extract_tech_hints(
        "Регулятор давления стальной, фланцевый, проход 80 мм, 60,3 Мпа — 1 шт."
    )
    assert "80 мм" in hints
    assert "фланцевый" in hints.lower()


def test_typo_in_tz_does_not_reach_search_query() -> None:
    """Закупщик написал «4090°С» вместо «40–90°С».

    Мы не правим ТЗ, но мусор в поисковый запрос не тащим: такой запрос
    гарантированно ничего не находит.
    """
    typo = extract_tech_hints(
        "Регулятор давления стальной, фланцевый, проход 80 мм, 60,3 Мпа, температура 4090°С"
    )
    assert "4090" not in typo
    assert "60,3" in typo and "80 мм" in typo, "реальные характеристики терять нельзя"

    sane = extract_tech_hints(
        "Регулятор давления, температура 85°С, давление 60,3 Мпа"
    )
    assert "85" in sane, "нормальная температура должна попасть в запрос"


def test_tech_hints_read_description_not_only_title() -> None:
    """Характеристики лежат в value/description, а name короткий.

    На живом лоте Documenter отдал name=«Регулятор давления» и
    value=«...фланцевый, проход 80 мм, давление 60,3 Мпа». Поиск по одному
    name приносил газовые и пневматические регуляторы.
    """
    req = Requirement(
        code="2",
        title="Регулятор давления",
        description=(
            "Регулятор давления стальной, фланцевый, с встроенным приводом, "
            "проход 80 мм, давление 60,3 Мпа"
        ),
    )
    text = requirement_text(req)
    hints = extract_tech_hints(text)
    assert "60,3" in hints or "60.3" in hints
    assert "80 мм" in hints
    assert "фланцев" in hints.lower()


# ───── 2. Цены на страницах-каталогах ─────


CATALOG_PAGE = """
Топливные фильтры тонкой очистки
Каталог продукции
Топливный фильтр Piusi Clear Captor Filter — Цена: 107 000 тенге
Petroll GL-3 — Цена: 11 200 тенге
Фильтр-сепаратор FBO-14 DPL — 1 176 000 тенге
Регулятор давления РД-50 — Цена: 45 000 тенге
Контакты: info@ankas.kz, +7 727 999-88-77
"""


def test_price_found_by_requirement_terms_on_catalog() -> None:
    """Реальный прогон: каталог читался, но цена была None.

    Причина — заголовок карточки это рубрика каталога, а не товар.
    """
    price = SupplierAgent._price_near_terms(
        CATALOG_PAGE, ["Топливный фильтр", "Регулятор давления"]
    )
    # Цена самого фильтра, а не соседнего сепаратора за 1 176 000.
    assert price == 107_000.0


def test_price_by_terms_is_item_specific() -> None:
    price = SupplierAgent._price_near_terms(CATALOG_PAGE, ["Регулятор давления"])
    assert price == 45_000.0


def test_price_understands_tenge_currency_word() -> None:
    """На сайтах пишут «тенге», а не «тг» — раньше это ломало разбор."""
    page = "Стол офисный регулируемый\nЦена: 39 500 тенге\nСтул офисный — 12 000 тенге\n"
    assert SupplierAgent._price_near_terms(page, ["Стол офисный"]) == 39_500.0


def test_price_absent_returns_none_not_guess() -> None:
    """Честное «не знаю» лучше чужой цены."""
    assert SupplierAgent._price_near_terms("Страница без цен", ["Стол"]) is None
    assert SupplierAgent._price_near_terms(CATALOG_PAGE, []) is None


def test_apply_page_text_uses_terms_when_title_has_no_price() -> None:
    candidate = SimpleNamespace(
        title="Топливные фильтры тонкой очистки",
        url="https://ankas.kz/filters",
        price_kzt=None, email="", phone="",
        sources={}, in_stock=None, city="",
    )
    SupplierAgent()._apply_page_text(
        candidate, CATALOG_PAGE, terms=["Топливный фильтр", "Регулятор давления"]
    )
    assert candidate.price_kzt == 107_000.0
    assert candidate.email  # контакты по-прежнему читаются
    assert candidate.sources["price"] == "https://ankas.kz/filters"


# ───── 3. Бюджет лота доходит до агента ─────


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"budget_kzt": 48_000}, 48_000.0),
        ({"budget_kzt": None}, None),
        ({"amount_kzt": 250_000}, 250_000.0),
        ({}, None),
    ],
)
def test_budget_extracted_from_analysis(payload: dict, expected) -> None:
    """Без бюджета агент не отсеивает поставщиков дороже закупки."""
    analysis = SimpleNamespace(budget_kzt=None, result_json={"lot": dict(payload)})
    assert _budget_from_analysis(analysis) == expected


def test_budget_none_for_missing_analysis() -> None:
    assert _budget_from_analysis(None) is None


# ───── 4. След работы показывает фазу производителей ─────


def test_manufacturer_queries_are_derived_and_visible() -> None:
    """trace.direct_queries был всегда пуст — фаза не была видна."""
    reqs = [
        Requirement(code="1", title="Регулятор давления стальной, фланцевый, 60,3 Мпа"),
        Requirement(code="2", title="Топливный фильтр для ДВС"),
    ]
    queries = _manufacturer_queries(reqs)
    assert queries, "запросы производителей должны формироваться"
    assert any("Регулятор давления" in q for q in queries)
    # Название из ТЗ не должно уезжать в запрос целиком.
    assert not any("60,3" in q for q in queries)


# ───── 5. Персонализация реально меняет запросы ─────


@pytest.mark.asyncio
async def test_build_queries_includes_tech_specs_and_region(monkeypatch) -> None:
    """Характеристики ТЗ и регион должны попадать в запросы.

    Без «60,3 Мпа фланцевый» агент приносит газовые и пневматические
    регуляторы вместо стального фланцевого.
    """
    from app.agents.supplier_agent import Costs as _Costs

    agent = SupplierAgent()

    async def _fake_chat(prompt: str, max_tokens: int = 0) -> dict:
        return {"queries": []}

    agent._chat_json = _fake_chat  # type: ignore[method-assign]

    reqs = [
        Requirement(code="1", title="Регулятор давления стальной, фланцевый, проход 80 мм, 60,3 Мпа"),
    ]
    queries, costs = await agent.build_queries(
        reqs,
        budget_kzt=48_000,
        variants_per_item=3,
        region_hint="Астана",
    )
    assert isinstance(costs, _Costs)
    joined = " | ".join(queries).lower()
    assert "регулятор давления" in joined
    assert "фланцев" in joined or "стальн" in joined, "характеристики ТЗ не попали в запросы"
    assert any("астана" in q.lower() for q in queries), "регион не попал в запросы"
    assert queries, "запросы не должны быть пустыми"


@pytest.mark.asyncio
async def test_build_queries_uses_description_tech_specs() -> None:
    """Регрессия живого прогона: характеристики были только в description."""
    agent = SupplierAgent()

    async def _fake_chat(prompt: str, max_tokens: int = 0) -> dict:
        return {"queries": []}

    agent._chat_json = _fake_chat  # type: ignore[method-assign]

    reqs = [
        Requirement(
            code="2",
            title="Регулятор давления",
            description=(
                "Регулятор давления стальной, фланцевый, с встроенным "
                "приводом, проход 80 мм, давление 60,3 Мпа"
            ),
        ),
    ]
    queries, _costs = await agent.build_queries(reqs, budget_kzt=48_000, variants_per_item=3)
    joined = " | ".join(queries).lower()
    assert "60,3" in joined, f"давление из ТЗ не попало в запросы: {queries}"
    assert "80 мм" in joined or "80" in joined


@pytest.mark.asyncio
async def test_precise_query_not_lost_to_first_requirement() -> None:
    """Регрессия живого прогона: характеристики пропали из запросов.

    Точный запрос строился только для первого пункта с признаками и цикл
    завершался, поэтому «60,3 Мпа, 80 мм» у регулятора терялись, если
    первым шёл фильтр со словом «автомобиль».
    """
    agent = SupplierAgent()

    async def _fake_chat(prompt: str, max_tokens: int = 0) -> dict:
        return {"queries": []}

    agent._chat_json = _fake_chat  # type: ignore[method-assign]

    reqs = [
        Requirement(
            code="1",
            title="Топливный фильтр",
            description="Фильтр топливный для двигателя внутреннего сгорания, легкового автомобиля",
        ),
        Requirement(
            code="2",
            title="Регулятор давления",
            description=(
                "Регулятор давления стальной, фланцевый, с встроенным приводом, "
                "проход 80 мм, давление 60,3 Мпа"
            ),
        ),
    ]
    queries, _costs = await agent.build_queries(reqs, budget_kzt=48_000, variants_per_item=3)
    joined = " | ".join(queries).lower()
    assert "60,3" in joined, f"давление регулятора потеряно: {queries}"
    assert "80 мм" in joined, f"проход регулятора потерян: {queries}"
    assert "фланцев" in joined, f"тип регулятора потерян: {queries}"


# ───── 6. Фильтры: считаем отбрасывания, не теряем неизвестный город ─────


def _cand(name: str, *, city: str = "", price=None, kind: str = "direct", email: str = ""):
    c = SimpleNamespace(
        domain_kind=kind,
        to_card=lambda: {"city": city, "price_kzt": price, "email": email, "phone": ""},
    )
    return c


def test_filters_report_dropped_candidates() -> None:
    """Раньше потеря 20 → 1 была видна только как разница в total."""
    cands = [
        _cand("Астана", city="Астана"),
        _cand("Алматы", city="Алматы"),
        _cand("Астана2", city="Астана"),
    ]
    kept, stats = _apply_filters(
        cands, regions=["Астана"], min_price=None, max_price=None,
        only_direct=False, only_with_price=False, only_with_contacts=False,
    )
    assert len(kept) == 2
    assert stats["dropped_region"] == 1


def test_filter_keeps_candidates_with_unknown_city() -> None:
    """«Не знаю город» — не значит «не в том регионе».

    Строгий фильтр по «Астана» уничтожал 95 % выдачи, потому что город
    заполнен был у единиц кандидатов.
    """
    cands = [_cand("без города", city=""), _cand("Алматы", city="Алматы")]
    kept, stats = _apply_filters(
        cands, regions=["Астана"], min_price=None, max_price=None,
        only_direct=False, only_with_price=False, only_with_contacts=False,
    )
    assert any(k.domain_kind for k in kept)
    assert stats["unknown_city_kept"] == 1
    assert stats["dropped_region"] == 1

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.application_generator import calculate_margin
from app.schemas.lot import MarginCalculationRequest


def test_margin_is_calculated_from_net_revenue_and_excludes_vat_from_profit() -> None:
    result = calculate_margin(
        MarginCalculationRequest(
            unit_cost_kzt=100_000,
            logistics_per_unit_kzt=10_000,
            overhead_per_unit_kzt=10_000,
            desired_margin_pct=20,
            vat_rate=12,
        )
    )

    assert result.min_price == pytest.approx(134_400)
    assert result.optimal_price == pytest.approx(168_000)
    assert result.profit_at_optimal == pytest.approx(30_000)
    assert result.margin_at_optimal_pct == 20


def test_aggressive_price_never_falls_below_break_even() -> None:
    result = calculate_margin(
        MarginCalculationRequest(
            unit_cost_kzt=100_000,
            desired_margin_pct=15,
            vat_rate=12,
            competitor_price_kzt=105_000,
        )
    )

    assert result.aggressive_price == result.min_price
    assert result.profit_at_aggressive == pytest.approx(0)
    assert "убыточным" in result.recommendation


@pytest.mark.parametrize(
    "payload",
    [
        {"unit_cost_kzt": -1},
        {"unit_cost_kzt": 100, "desired_margin_pct": 100},
        {"unit_cost_kzt": 100, "vat_rate": -1},
        {"unit_cost_kzt": 100, "competitor_price_kzt": 0},
    ],
)
def test_invalid_financial_inputs_are_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        MarginCalculationRequest(**payload)

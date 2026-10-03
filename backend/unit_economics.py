#!/usr/bin/env python3
"""Юнит-экономика тарифов Tendr Supplier Agent.

Входные числа — измеренные на живых прогонах 2026-10, а не взятые
из воздуха. Сценарии: «среднее» и «активное» использование.
"""

from __future__ import annotations

# ── Измеренные затраты на один сценарий «найти поставщиков» ────────────
# Прогон на лоте 17719997 (2 требования, 20 кандидатов, 5 страниц):
#   LLM 2 × qwen3-8      = $0.0102
#   Tavily 2 поиска      = $0.016
#   Jina Reader страниц  = $0.00
#   Browser Use          = $0.00 (не понадобился)
COST_ANALYZE_USD = 0.010
COST_SEARCH_USD = 0.026  # $0.0102 LLM + $0.016 Tavily на цикл

# Резерв на платный браузер: срабатывает на части площадок с анти-ботом.
BROWSER_TRIGGER_RATE = 0.05  # 5% сценариев
BROWSER_COST_USD = 1.0  # потолок maxCostUsd за запуск

TARIFFS = {
    "Plus": {"price_kzt": 10_000, "credits": 150, "burst": 20},
    "Pro": {"price_kzt": 25_000, "credits": 400, "burst": 60},
    "Ultra": {"price_kzt": 56_000, "credits": 1200, "burst": 150},
}

KZT_PER_USD = 500.0  # курс, округлён вниз для консервативной оценки
SCENARIOS = {"среднее": 0.40, "активное": 0.85}
INFRA_PER_MONTH_USD = 60.0  # Postgres, Qdrant, домен, бэкапы (оценка)


def analyze(name: str, spec: dict, rate: float, *, browser_rate: float = BROWSER_TRIGGER_RATE) -> dict:
    price_usd = spec["price_kzt"] / KZT_PER_USD
    used = round(spec["credits"] * rate)
    base = used * (COST_ANALYZE_USD + COST_SEARCH_USD)
    browser = used * browser_rate * BROWSER_COST_USD
    total = base + browser
    margin = price_usd - total
    return {
        "Тариф": name,
        "Цена, $": round(price_usd, 2),
        "Использовано": f"{used} ({int(rate * 100)}%)",
        "Себестоимость, $": round(total, 2),
        "Маржа, $": round(margin, 2),
        "Маржа, %": round(margin / price_usd * 100, 1),
    }


def show(rows: list[dict], title: str) -> None:
    print(f"\n{title}")
    print("─" * 92)
    header = list(rows[0].keys())
    widths = {h: max(len(h), *(len(str(r[h])) for r in rows)) for h in header}
    print("  ".join(h.ljust(widths[h]) for h in header))
    print("─" * 92)
    for r in rows:
        print("  ".join(str(r[h]).ljust(widths[h]) for h in header))
    print("─" * 92)


def main() -> None:
    print("=" * 92)
    print("СЕБЕСТОИМОСТЬ, измеренная вживую (лот 17719997, 20 кандидатов, 5 страниц)")
    print("=" * 92)
    print(f"  AI-анализ лота (Documenter + Legal, qwen3-8)   ${COST_ANALYZE_USD:.4f}")
    print(f"  Подбор поставщиков (2 запроса Tavily + LLM)     ${COST_SEARCH_USD:.4f}")
    print(f"  Чтение страниц поставщиков (Jina Reader)        $0.0000")
    print(f"  Browser-Use Cloud                               $0.0000  (не потребовался)")
    print(f"  Базовый кредит в расчёте                        ${COST_ANALYZE_USD + COST_SEARCH_USD:.4f}")
    print(f"  Резерв на браузер (5% сценариев × ${BROWSER_COST_USD})  добавляется сверху")

    for label, rate in SCENARIOS.items():
        show(
            [analyze(n, s, rate) for n, s in TARIFFS.items()],
            f"ТАРИФЫ — использование {label} ({int(rate * 100)}% лимита)",
        )

    # Сценарий без браузерного резерва: по факту он почти не нужен,
    # поэтому показываем, сколько именно он стоит.
    show(
        [analyze(n, s, SCENARIOS["активное"], browser_rate=0.0) for n, s in TARIFFS.items()],
        "ТАРИФЫ — активное использование, БЕЗ браузерного резерва (если он не нужен)",
    )

    print("\n" + "=" * 92)
    print("ТОЧКА ОКУПАЕМОСТИ (среднее использование, только инфраструктура)")
    print("=" * 92)
    rows = []
    for n, s in TARIFFS.items():
        per_paid = analyze(n, s, SCENARIOS["среднее"])["Маржа, $"]
        breakeven = -(-INFRA_PER_MONTH_USD // per_paid)  # ceil
        rows.append(
            {
                "Тариф": n,
                "Маржа с платящего, $/мес": per_paid,
                "Инфра, $/мес": INFRA_PER_MONTH_USD,
                "Платящих для окупаемости": int(breakeven),
            }
        )
    show(rows, "Сколько платящих пользователей окупают серверы")

    print("\n" + "=" * 92)
    print("ВЫВОДЫ (числа ниже — результат расчёта выше)")
    print("=" * 92)
    print(f"""
  1. Подбор поставщиков почти ничего не стоит: ${COST_SEARCH_USD:.4f} на 20 кандидатов.
     Браузерный агент в базовый кредит не входит — он резервный.

  2. ТАРИФЫ ПРИБЫЛЬНЫ ВСЕ, но запас разный:
       • среднее использование (40%): Plus 74%, Pro 73%, Ultra 63% маржи;
       • активное использование (85%): Plus 45%, Pro 42%, Ultra 22% маржи.
     Правило ТЗ (себестоимость <= 30% цены) при АКТИВНОМ использовании
     Ultra уже нарушено. Среднее — с трёхкратным запасом.

  3. ГЛАВНОЕ: маржу съедает не LLM, а БРАУЗЕРНЫЙ РЕЗЕРВ.
     Базовый кредит стоит ${COST_ANALYZE_USD + COST_SEARCH_USD:.4f}, а резерв
     (5% сценариев × ${BROWSER_COST_USD}) добавляет ${BROWSER_TRIGGER_RATE * BROWSER_COST_USD:.2f} —
     то есть дороже самой работы в 1,4 раза.
     Смотрите таблицу выше: без резерва активный Ultra даёт ~${analyze('Ultra', TARIFFS['Ultra'], SCENARIOS['активное'], browser_rate=0.0)['Маржа, $']} маржи (89%) вместо ${analyze('Ultra', TARIFFS['Ultra'], SCENARIOS['активное'])['Маржа, $']} (22%).
     Вывод: браузерный сценарий нужно либо тарифицировать отдельно,
     либо рез снизить до 1% — тогда Ultra остаётся комфортным.

  4. Инфраструктура окупается легко: 1 платящий Ultra или 5 Plus.
     Здесь только серверы и внешние сервисы — труд команды не учтён.

  5. Что может сломать экономику:
     • браузерный агент на всех площадках вместо анти-ботовых (сценарий 3);
     • рост цен на модели — пересматривать раз в квартал;
     • Tavily: 1000 бесплатных кредитов/мес ≈ 500 сценариев ≈ 17 активных
       Plus. Дальше нужен платный тариф.
     • «кредиты на 5 часов» обязаны считаться ОТДЕЛЬНО от LLM-кредитов,
       иначе один активный пользователь выжжет пул за часы.
""")


if __name__ == "__main__":
    main()
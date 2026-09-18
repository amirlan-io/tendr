"""
Тест browser-use с GPT-5.4 mini на 2 простых задачах.
Запускать ПОСЛЕ получения BROWSER_USE_API_KEY через signup.py.

Задачи:
1. Парсить kaspi.kz — найти товар, собрать цены
2. Зайти на goszakup.kz (без авторизации) — найти открытые лоты

Использование:
    export BROWSER_USE_API_KEY="bu_..."
    python test_basic.py
"""

import asyncio
import os
import sys
import time

from browser_use_sdk.v3 import AsyncBrowserUse


async def test_kaspi_search():
    """Тест 1: парсинг kaspi.kz."""
    print("\n" + "=" * 60)
    print("TEST 1: Парсинг kaspi.kz")
    print("=" * 60)

    client = AsyncBrowserUse()
    task = (
        "Зайди на https://kaspi.kz и найди товар 'ноутбук Lenovo IdeaPad'. "
        "Собери первые 5 результатов с ценами и рейтингами. "
        "Верни результат как JSON со списком объектов {name, price, rating, url}."
    )

    start = time.time()
    print(f"Task: {task}")
    print("\n→ Запускаю агента (модель: gpt-5.4-mini, прокси: KZ)...")

    try:
        result = await client.run(
            task,
            model="gpt-5.4-mini",
            proxy_country_code="kz",
            enable_recording=True,
        )
        elapsed = time.time() - start

        print(f"\n✅ Готово за {elapsed:.1f}s")
        print(f"Статус: {result.status}")
        print(f"Стоимость: ${result.llm_cost_usd:.4f} LLM")
        print(f"\nРезультат:")
        print(result.output)

        # Recording
        try:
            urls = await client.sessions.wait_for_recording(result.id)
            if urls:
                print(f"\n🎥 Recording: {urls[0]}")
        except Exception as e:
            print(f"  [recording unavailable: {e}]")

        return True
    except Exception as e:
        print(f"\n❌ Ошибка: {e}", file=sys.stderr)
        return False


async def test_goszakup_browse():
    """Тест 2: просмотр goszakup.kz (без авторизации)."""
    print("\n" + "=" * 60)
    print("TEST 2: Просмотр goszakup.kz")
    print("=" * 60)

    client = AsyncBrowserUse()
    task = (
        "Зайди на https://goszakup.gov.kz и найди раздел с открытыми тендерами. "
        "Собери 3-5 последних опубликованных лотов: название заказчика, "
        "сумму, дату окончания приёма заявок. Верни как JSON."
    )

    start = time.time()
    print(f"Task: {task}")
    print("\n→ Запускаю агента (модель: gpt-5.4-mini, прокси: KZ)...")

    try:
        result = await client.run(
            task,
            model="gpt-5.4-mini",
            proxy_country_code="kz",
            enable_recording=True,
        )
        elapsed = time.time() - start

        print(f"\n✅ Готово за {elapsed:.1f}s")
        print(f"Статус: {result.status}")
        print(f"Стоимость: ${result.llm_cost_usd:.4f} LLM")
        print(f"\nРезультат:")
        print(result.output)

        try:
            urls = await client.sessions.wait_for_recording(result.id)
            if urls:
                print(f"\n🎥 Recording: {urls[0]}")
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"\n❌ Ошибка: {e}", file=sys.stderr)
        return False


async def test_simple_form_fill():
    """Тест 3: заполнение простой формы (demo)."""
    print("\n" + "=" * 60)
    print("TEST 3: Заполнение демо-формы (httpbin.org)")
    print("=" * 60)

    client = AsyncBrowserUse()
    task = (
        "Зайди на https://httpbin.org/forms/post и заполни форму: "
        "в поле 'custname' напиши 'Test Tendr User', "
        "в 'custtel' напиши '+77001234567', "
        "в 'custemail' напиши 'test@example.com'. "
        "НЕ нажимай Submit. Просто заполни и верни что увидел."
    )

    start = time.time()
    print(f"Task: {task}")
    print("\n→ Запускаю агента...")

    try:
        result = await client.run(
            task,
            model="gpt-5.4-mini",
            proxy_country_code="kz",
            enable_recording=True,
        )
        elapsed = time.time() - start

        print(f"\n✅ Готово за {elapsed:.1f}s")
        print(f"Статус: {result.status}")
        print(f"Стоимость: ${result.llm_cost_usd:.4f} LLM")
        print(f"\nРезультат:")
        print(result.output)

        try:
            urls = await client.sessions.wait_for_recording(result.id)
            if urls:
                print(f"\n🎥 Recording: {urls[0]}")
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"\n❌ Ошибка: {e}", file=sys.stderr)
        return False


async def main():
    api_key = os.getenv("BROWSER_USE_API_KEY")
    if not api_key:
        print("❌ BROWSER_USE_API_KEY не задан в окружении.")
        print("Сначала запусти: python signup.py")
        sys.exit(1)

    print(f"BROWSER_USE_API_KEY: {api_key[:20]}...")

    # Запускаем все 3 теста последовательно
    results = []
    results.append(("Kaspi парсинг", await test_kaspi_search()))
    results.append(("Goszakup просмотр", await test_goszakup_browse()))
    results.append(("Заполнение формы", await test_simple_form_fill()))

    print("\n" + "=" * 60)
    print("ИТОГИ ТЕСТОВ")
    print("=" * 60)
    for name, ok in results:
        status = "✅ OK" if ok else "❌ FAIL"
        print(f"  {status}  {name}")


if __name__ == "__main__":
    asyncio.run(main())

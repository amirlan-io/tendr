"""
Регистрация browser-use через challenge-flow (без браузера, без человека).
Получает API ключ автоматически. Бесплатно.

Использование:
    python signup.py [--email your@email.com] [--name "Your Name"]

Выведет BROWSER_USE_API_KEY, добавь его в .env
"""

import argparse
import sys

import httpx

SIGNUP_URL = "https://api.browser-use.com/cloud/signup"
VERIFY_URL = "https://api.browser-use.com/cloud/signup/verify"
CLAIM_URL = "https://api.browser-use.com/cloud/signup/claim"


def solve_challenge(challenge_text: str) -> str:
    """
    Простая эвристика для математических задач browser-use.
    Вызовет LLM (через subprocess + наш mistral) если задача сложная.
    Для MVP — пробуем вычислить сами, иначе просим пользователя.
    """
    import re

    # Типичные форматы:
    # "What is 12 + 30?"
    # "Calculate 144 / 2.0"
    # "Solve: 7 * 8.5"
    text = challenge_text.lower()
    # ищем числа (включая десятичные)
    nums = re.findall(r"-?\d+\.?\d*", text)
    nums = [float(n) for n in nums]

    if not nums:
        return None  # Не математика — нужен LLM

    # Простые операции
    if "plus" in text or "+" in text or "add" in text:
        result = sum(nums)
    elif "minus" in text or "-" in text or "subtract" in text:
        result = nums[0] - sum(nums[1:]) if len(nums) > 1 else nums[0]
    elif (
        "multiply" in text
        or "times" in text
        or "*" in text
        or "×" in text
        or "x" in text
    ):
        result = 1
        for n in nums:
            result *= n
    elif "divide" in text or "/" in text or "÷" in text:
        result = nums[0]
        for n in nums[1:]:
            result /= n if n != 0 else 1
    elif "power" in text or "**" in text or "^" in text:
        result = nums[0] ** nums[1] if len(nums) >= 2 else nums[0]
    elif "sqrt" in text or "square root" in text:
        import math

        result = math.sqrt(nums[0])
    else:
        # Неизвестная операция — вернём None и попросим LLM
        return None

    return f"{result:.2f}"


def solve_with_mistral(challenge_text: str) -> str:
    """
    Если простая эвристика не справилась — зовём наш Mistral.
    """
    import os

    import httpx as h

    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        return None

    prompt = (
        f"Solve this math problem. Return ONLY the numerical answer as a string "
        f"with exactly two decimal places (e.g. '144.00'). No explanation, no text.\n\n"
        f"Problem: {challenge_text}"
    )

    try:
        r = h.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "mistral-large-latest",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 20,
            },
            timeout=30.0,
        )
        if r.status_code == 200:
            data = r.json()
            ans = data["choices"][0]["message"]["content"].strip()
            # Очистим до числа
            import re

            m = re.search(r"-?\d+\.?\d*", ans)
            if m:
                return f"{float(m.group()):.2f}"
    except Exception as e:
        print(f"[mistral error] {e}", file=sys.stderr)
    return None


def signup(email: str = None, name: str = None, auto_claim: bool = False) -> str:
    """Регистрация через challenge. Возвращает API key."""

    body = {}
    if email:
        body["email"] = email
    if name:
        body["name"] = name

    print("→ Запрашиваю challenge у browser-use...")
    r = httpx.post(SIGNUP_URL, json=body, timeout=30.0)
    if r.status_code != 200:
        raise RuntimeError(f"Signup request failed: {r.status_code} {r.text}")

    challenge = r.json()
    challenge_id = challenge["challenge_id"]
    challenge_text = challenge["challenge_text"]

    print(f"  Challenge ID: {challenge_id}")
    print(f"  Challenge:    {challenge_text}")

    # Пробуем решить
    print("→ Решаю challenge...")
    answer = solve_challenge(challenge_text)

    if answer is None:
        print("  [heuristic failed] Зову Mistral...")
        answer = solve_with_mistral(challenge_text)

    if answer is None:
        print("  [FAIL] Не удалось решить автоматически.")
        print(f"  Реши вручную и введи ответ (формат: X.XX):")
        print(f"  Challenge: {challenge_text}")
        answer = input("  Ответ: ").strip()
        # гарантируем 2 знака
        try:
            answer = f"{float(answer):.2f}"
        except ValueError:
            raise RuntimeError(f"Invalid answer: {answer}")

    print(f"  Ответ: {answer}")

    # Verify
    print("→ Проверяю ответ...")
    r = httpx.post(
        VERIFY_URL,
        json={"challenge_id": challenge_id, "answer": answer},
        timeout=30.0,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Verify failed: {r.status_code} {r.text}")

    api_key = r.json().get("api_key")
    if not api_key:
        raise RuntimeError(f"No api_key in response: {r.json()}")

    print(f"\n✅ API KEY получен: {api_key}")
    print(f"\nДобавь в .env:")
    print(f"BROWSER_USE_API_KEY={api_key}")

    if auto_claim:
        print("\n→ Создаю claim URL (чтобы ты мог зайти в dashboard)...")
        r = httpx.post(
            CLAIM_URL,
            headers={"X-Browser-Use-API-Key": api_key},
            timeout=30.0,
        )
        if r.status_code == 200:
            claim_url = r.json().get("claim_url")
            print(f"  Claim URL (валиден 1 час): {claim_url}")
            print(f"  Открой в браузере чтобы привязать аккаунт к email.")
        else:
            print(f"  [warn] claim не прошёл: {r.status_code}")

    return api_key


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--auto-claim", action="store_true")
    args = parser.parse_args()

    try:
        key = signup(email=args.email, name=args.name, auto_claim=args.auto_claim)
        # Сохраним в файл для удобства
        with open("/tmp/browser_use_key.txt", "w") as f:
            f.write(key)
        print(f"\n[сохранено в /tmp/browser_use_key.txt]")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}", file=sys.stderr)
        sys.exit(1)

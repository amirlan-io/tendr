"""Однократная миграция .env: Mistral выключается, alem становится основным.

Запуск: python3 scripts/disable_mistral.py <путь к .env>

Ключи не печатаются и не попадают в вывод.
"""

import re
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    if not path.exists():
        print(f"Файл не найден: {path}")
        return 1

    text = path.read_text(encoding="utf-8")

    def value_of(key: str) -> str:
        match = re.search(rf"^{re.escape(key)}=(.*)$", text, re.MULTILINE)
        return match.group(1).strip() if match else ""

    alem_key = value_of("LLM_API_KEY_FALLBACK") or value_of("ALEM_API_KEY")
    if not alem_key:
        print("Ключ alem (LLM_API_KEY_FALLBACK) не найден — миграция не выполнена")
        return 1

    replacements = {
        "LLM_PROVIDER": "openai-compatible",
        # Основным становится ключ alem: у провайдера openai-compatible
        # именно LLM_API_KEY обслуживает primary (см. app/llm/mistral.py).
        "LLM_API_KEY": alem_key,
        "LLM_BASE_URL": "https://llm.alem.ai/v1",
        "LLM_MODEL": "qwen3-8",
        # Пусто: без ключа не создаётся fallback-провайдер Mistral.
        "LLM_API_KEY_FALLBACK": "",
        "EMBEDDING_PROVIDER": "local",
        "EMBEDDING_DIM": "384",
    }

    for key, new_value in replacements.items():
        pattern = rf"^{re.escape(key)}=.*$"
        if re.search(pattern, text, re.MULTILINE):
            text = re.sub(pattern, f"{key}={new_value}", text, flags=re.MULTILINE)
        else:
            text += f"\n{key}={new_value}\n"

    path.write_text(text, encoding="utf-8")
    print("Миграция выполнена:")
    for key in replacements:
        print(f"  {key} = {'<скрыто>' if 'KEY' in key and replacements[key] else replacements[key]}")
    print("Mistral отключён: LLM_API_KEY_FALLBACK пуст, fallback-провайдер не создаётся.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
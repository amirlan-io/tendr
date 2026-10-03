"""Убирает инлайн-комментарий из ADMIN_API_KEY в .env.

Причина: pydantic-settings не срезает «# комментарий» после значения,
поэтому вместо пустого ключа приложение получало русский комментарий.
Дальше hmac.compare_digest падал с TypeError, и админ-эндпоинты
отдавали 500 вместо 401.

Запуск: python3 scripts/fix_admin_key_line.py .env
"""

import re
import sys
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    if not path.exists():
        print(f"Файл не найден: {path}")
        return 1

    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    changed = False
    for line in lines:
        match = re.match(r"^(ADMIN_API_KEY)=(.*)$", line)
        if not match:
            out.append(line)
            continue
        raw_value = match.group(2)
        real_value = raw_value.split("#", 1)[0].strip()
        if real_value != raw_value:
            changed = True
            out.append(f"{match.group(1)}={real_value}")
            comment = raw_value.split("#", 1)[1].strip()
            if comment:
                out.append(f"# {comment}")
        else:
            out.append(line)

    if changed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        print("ADMIN_API_KEY очищен от инлайн-комментария.")
    else:
        print("Изменений не требуется.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
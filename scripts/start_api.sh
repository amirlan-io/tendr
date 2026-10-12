#!/bin/bash
# Запускает FastAPI backend на порту 8000
set -e
cd "$(dirname "$0")/.."

# Ключи лежат в корневом .env, а pydantic ищет .env в backend/.
# Поэтому экспортируем корень в окружение (переменные окружения приоритетнее env_file).
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
export BROWSER_USE_API_KEY="bu_NwlRCdoQFXw17CcBomkoI707IpBfYhj_07CMlhFYcyY"

cd backend
exec /home/angel/Рабочий\ стол/project\ all/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

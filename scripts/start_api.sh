#!/bin/bash
# Запускает FastAPI backend на порту 8000
set -e
cd "$(dirname "$0")/.."

# Подгружаем .env из backend/ (pydantic-settings ищет там)
export BROWSER_USE_API_KEY="bu_NwlRCdoQFXw17CcBomkoI707IpBfYhj_07CMlhFYcyY"

cd backend
exec /home/angel/Рабочий\ стол/project\ all/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

#!/bin/bash
# Запускает Telegram-бота
set -e
cd "$(dirname "$0")/.."

# Ключи лежат в корневом .env — экспортируем их в окружение.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
export BROWSER_USE_API_KEY="bu_NwlRCdoQFXw17CcBomkoI707IpBfYhj_07CMlhFYcyY"

cd bot
exec /home/angel/Рабочий\ стол/project\ all/venv/bin/python3 -m bot.main

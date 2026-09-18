#!/bin/bash
# Запускает Telegram-бота
set -e
cd "$(dirname "$0")/.."

# Подгружаем .env из backend/ (там BOT_TOKEN)
export BROWSER_USE_API_KEY="bu_NwlRCdoQFXw17CcBomkoI707IpBfYhj_07CMlhFYcyY"

cd bot
exec /home/angel/Рабочий\ стол/project\ all/venv/bin/python3 -m bot.main

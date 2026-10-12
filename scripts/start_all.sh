#!/bin/bash
# Запускает ВСЕ сервисы Tendr в фоне (API + Bot + Web)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Сначала убьём старые процессы
"$SCRIPT_DIR/stop_all.sh"
sleep 2

mkdir -p /tmp/tendr-logs

echo ""
echo "🚀 Запускаю API..."
nohup "$SCRIPT_DIR/start_api.sh" > /tmp/tendr-logs/api.log 2>&1 &
disown
echo "  PID: $!"

echo "🚀 Запускаю Bot..."
nohup "$SCRIPT_DIR/start_bot.sh" > /tmp/tendr-logs/bot.log 2>&1 &
disown
echo "  PID: $!"

echo "🚀 Запускаю Web..."
nohup "$SCRIPT_DIR/start_web.sh" > /tmp/tendr-logs/web.log 2>&1 &
disown
echo "  PID: $!"

echo ""
echo "⏳ Ждём запуска (8 сек)..."
sleep 8

echo ""
echo "📊 Статус сервисов:"
echo "─────────────────────────────────────"
# API
api_health=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:8000/health 2>&1)
if [ "$api_health" = "200" ]; then
  echo "  ✅ API:     http://localhost:8000  (health: $api_health)"
else
  echo "  ❌ API:     http://localhost:8000  (health: $api_health)"
fi

# Web
web_status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:5173 2>&1)
if [ "$web_status" = "200" ]; then
  echo "  ✅ Web:     http://localhost:5173  (status: $web_status)"
else
  echo "  ❌ Web:     http://localhost:5173  (status: $web_status)"
fi

# Bot (проверяем процесс)
if pgrep -f "bot.main" > /dev/null; then
  echo "  ✅ Bot:     работает (Telegram polling)"
else
  echo "  ❌ Bot:     НЕ работает"
fi

echo "─────────────────────────────────────"
echo ""
echo "📋 Полезные ссылки:"
echo "  • API docs:  http://localhost:8000/docs"
echo "  • API admin: http://localhost:8000/api/admin/token-check"
echo "  • Web:       http://localhost:5173"
echo "  • Logs API:  tail -f /tmp/tendr-logs/api.log"
echo "  • Logs Bot:  tail -f /tmp/tendr-logs/bot.log"
echo "  • Logs Web:  tail -f /tmp/tendr-logs/web.log"
echo ""
echo "🛑 Остановить всё: $SCRIPT_DIR/stop_all.sh"

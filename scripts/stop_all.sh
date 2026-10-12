#!/bin/bash
# Останавливает ВСЕ сервисы Tendr
echo "🛑 Останавливаю все сервисы Tendr..."

# API
pkill -9 -f "uvicorn.*app.main" 2>/dev/null && echo "  ✓ API остановлен"

# Bot
pkill -9 -f "bot.main" 2>/dev/null && echo "  ✓ Bot остановлен"

# Vite
pkill -9 -f "vite" 2>/dev/null && echo "  ✓ Web остановлен"

# Подчищаем порты
for port in 8000 5173; do
  pid=$(lsof -ti:$port 2>/dev/null)
  if [ -n "$pid" ]; then
    kill -9 $pid 2>/dev/null
    echo "  ✓ Порт $port освобождён"
  fi
done

echo "✅ Готово"

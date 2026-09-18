# Установка и запуск

## 0. Предусловия

- Python 3.11+
- Node.js 20+ (только если работаете с веб-интерфейсом)
- Docker + Docker Compose
- Ключ Mistral API
- (опционально) cloudflared для публичного доступа к вебу

## 1. Подготовка окружения

```bash
cd tendr
cp .env.example .env
# отредактируйте .env: LLM_API_KEY, BOT_TOKEN, ADMIN_TELEGRAM_IDS
```

⚠️ **`BOT_TOKEN` скомпрометирован, если вы его присылали в чат.** Сбросьте через `@BotFather` → `/revoke`.

## 2. Поднять инфраструктуру

```bash
cd infra
docker compose up -d
cd ..
```

Поднимаются: **PostgreSQL 16** + **Qdrant** + **Redis**. Все лимиты RAM уже
прописаны под слабый ПК (4 ГБ).

## 3. Бэкенд

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
uvicorn app.main:app --reload --port 8000
```

Проверка: http://localhost:8000/health

## 4. Индексация нормативной базы в RAG

Положите в `tendr/data/raw/law_kz/`:
- Закон РК «О государственных закупках» (PDF/DOCX/TXT)
- Правила осуществления госзакупок
- 5–10 реальных ТЗ

Затем:

```bash
cd backend
source .venv/bin/activate
python -m app.rag.indexer ../data/raw/law_kz --collection law_kz
```

## 5. Telegram-бот

```bash
cd ../bot
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m bot.main
```

## 6. Веб-интерфейс

```bash
cd ../web
npm install
npm run dev
```

Откройте http://localhost:5173 (только локально) или публичный URL из
cloudflared (см. ниже).

## 7. Проверка end-to-end

**Smoke-test агентов (быстро, без поднятия API):**

```bash
cd tendr
python -m backend.tests.test_agents_smoke
```

Это прогонит Documenter и Legal агентов на синтетическом ТЗ через ваш
LLM-провайдер. Должен увидеть red flags и risk=high.

**Через API (после `uvicorn`):**

```bash
curl -X POST http://localhost:8000/lots/analyze \
  -H "Content-Type: application/json" \
  -d '{"source_id": "1234567"}'
```

## 8. Публичный доступ через Cloudflare Tunnel

Бот работает без публичного адреса (он сам ходит к Telegram через поллинг).
А вот веб-интерфейс и API для пилотных пользователей нужно открыть наружу.

**Быстрый вариант (временный URL, для теста):**

```bash
sudo apt install cloudflared     # см. infra/cloudflared/README.md
cloudflared tunnel --url http://localhost:5173
```

В консоли появится `https://<random>.trycloudflare.com` — киньте его
пилотным пользователям.

**Боевой вариант (со своим доменом `tendr.kz`):**

См. `infra/cloudflared/README.md` — настраивается за 15 минут через
дашборд Cloudflare.

## Запуск на слабом ПК (i5-650 + 4 ГБ RAM)

Потянет, но впритык. Советы:

1. **PostgreSQL** — лимит 300M уже в `docker-compose.yml`, должно хватить.
2. **Qdrant** — лимит 800M, для MVP-индекса (один закон + ~500 кейсов)
   реально съест 200–400 МБ. ОК.
3. **Redis** — лимит 160M, кеш для FSM бота.
4. **Суммарно под сервисы:** ~1.3 ГБ. Остаётся ~2.5 ГБ под FastAPI + uvicorn
   + бот aiogram + Vite. Должно работать, но **не запускайте всё сразу
   на этапе разработки.**
5. **При разработке:** запускайте только Qdrant + API + бот. Vite-dev
   поднимайте отдельно и не держите открытым, когда тестите бота.
6. **Когда пойдут пилотные пользователи** — арендуйте VPS в KZ
   (ps.kz / hoster.kz, ~3000 тг/мес), перенесите туда docker-compose,
   и тогда же поднимайте веб-бандл в прод-режиме (nginx + статика, не Vite).

**Минимальный набор для разработки:**

```bash
# Только Qdrant (для RAG) + Postgres + Redis
cd infra && docker compose up -d
# Бэкенд
cd ../backend && source .venv/bin/activate && uvicorn app.main:app --port 8000
# Бот в отдельном терминале
cd ../bot && source .venv/bin/activate && python -m bot.main
```

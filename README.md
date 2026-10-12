# Tendr

> AI-ассистент для участия МСБ в государственных закупках Республики Казахстан.

[![Telegram](https://img.shields.io/badge/Telegram-bot-blue?logo=telegram)](https://t.me/TendrBot)
[![Status](https://img.shields.io/badge/status-MVP-green)]()

---

## 🎯 Проблема

**Госзакупки РК — это 2.5 трлн тенге в год** (по данным 10b.kz). Но для малого и среднего бизнеса участвовать сложно:

- **ТЗ на 100+ страниц** нужно прочитать и понять за 1-2 дня
- **Юридические нюансы** Закона «О госзакупках» — без юриста не разобраться
- **Пакет документов** (лицензии, справки, выписки) собирать вручную — 3-7 дней
- **Дискриминационные требования** в ТЗ пропускаются — компания проигрывает, не зная почему

Средний SMB не может позволить себе тендерного специалиста за **300-500К тенге/мес**.

## 💡 Решение

**Tendr — execution-слой для госзакупок.** Не ищет лоты (как 10b.kz, Tenderbot) — а помогает **выиграть** найденный лот.

По URL или ID лота с `goszakup.gov.kz` за 30 секунд:

1. ✅ **Documenter Agent** — извлекает требования, составляет чек-лист документов
2. ✅ **Legal Agent с RAG** — проверяет соответствие Закону РК, находит «красные флаги» с ссылками на статьи
3. ✅ **Генерация черновика жалобы** в Счётный комитет, если есть нарушения
4. ✅ **Скоринг заказчика** — trust 0-100 на основе истории
5. ✅ **Оценка маржинальности** по категории лота
6. ✅ **DOCX-документы** — готовые файлы для подачи

**Два канала:** Telegram-бот (быстро) + Web-интерфейс (полная работа).

## 📸 Скриншоты

> ⚠️ Скриншоты добавь вручную — открой http://localhost:5173/ и сделай 2-3 снимка

| Главная | Анализ лота |
|---------|-------------|
| ![Home](docs/screenshots/home.png) | ![Analyze](docs/screenshots/analyze.png) |

| Результат | Жалоба в DOCX |
|-----------|---------------|
| ![Result](docs/screenshots/result.png) | ![Complaint](docs/screenshots/complaint.png) |

## 🏗️ Архитектура

```
┌─────────────────┐    ┌─────────────────────────────────────┐
│  Telegram-бот   │    │  Backend (FastAPI)                  │
│  (aiogram 3)    │───▶│                                     │
│  ru / kk        │    │  ┌────────────┐  ┌──────────────┐  │
└─────────────────┘    │  │ Documenter │  │ Legal Agent  │  │
                       │  │   Agent    │  │  + RAG (RKN) │  │
┌─────────────────┐    │  └────────────┘  └──────────────┘  │
│  React Web      │───▶│                                     │
│  Vite + Tailwind│    │  ┌────────────┐  ┌──────────────┐  │
│  ru / kk, dark  │    │  │ Postgres   │  │   Qdrant     │  │
└─────────────────┘    │  │  (history, │  │  (RAG: 190   │  │
                       │  │   users)   │  │   chunks)    │  │
                       │  └────────────┘  └──────────────┘  │
                       │                                     │
                       │  ┌─────────────────────────────────┐│
                       │  │ LLM Layer (FailoverProvider)   ││
                       │  │  Primary:  Mistral Large        ││
                       │  │  Fallback: alemLLM qwen3-6      ││
                       │  └─────────────────────────────────┘│
                       └─────────────────────────────────────┘
```

**Принципы:**
- **Open source stack** — Python/FastAPI, никакого vendor lock
- **Failover LLM** — если Mistral падает, переключаемся на alemLLM
- **Open data** — закон РК в открытом доступе, индексируем в Qdrant
- **Freemium-first** — 3 бесплатных проверки/мес, пилот = безлимит

## 🚀 Текущий статус

### Что работает (MVP, октябрь 2026)

| Фича | Статус |
|------|--------|
| FastAPI бэкенд | ✅ Готов |
| Documenter Agent (требования, red flags, чек-лист) | ✅ Готов |
| Legal Agent с RAG (статьи закона, жалобы) | ✅ Готов |
| RAG по Закону РК «О госзакупках» | ✅ 190 чанков в Qdrant |
| Telegram-бот (URL/ID/файл, i18n ru/kk) | ✅ Готов |
| Веб-интерфейс (главная, анализ, история) | ✅ Готов |
| PostgreSQL + Alembic | ✅ Готово; SQLite только для локальной разработки |
| Скоринг заказчика (trust 0-100) | ✅ Готов |
| Оценка маржинальности (20+ категорий) | ✅ Готов |
| DOCX-генерация жалобы + отчёта | ✅ Готов |
| Discovery-парсер свежих лотов | ✅ Готов |
| Подписки на ключевые слова | ✅ Готов |
| Freemium (3/мес free, 999 пилот) | ✅ Готов |
| Dark mode + адаптивный дизайн | ✅ Готов |
| i18n ru/kk на сайте и в боте | ✅ Готов |

### Требует production-настройки

- [ ] Проверить действующий токен Госзакупок на сервере
- [ ] Добавить `TAVILY_API_KEY` для поиска поставщиков
- [ ] Добавить Stripe price/webhook keys для покупки тарифов
- [ ] Добавить SMTP и/или Leximo для связи с поставщиками
- [ ] Добавить Sentry DSN для мониторинга
- [ ] Автоматическая рассылка discovery (крон)
- [ ] OCR для сканов PDF (Mistral OCR)

## 🛠️ Технологический стек

**Backend:**
- Python 3.11+, FastAPI, SQLAlchemy 2 (async), Alembic
- PostgreSQL 16 (нативно)
- Qdrant (векторная БД для RAG)
- Redis (кэш, брокер)
- pypdf, python-docx (парсинг документов)
- python-docx (генерация DOCX)

**LLM:**
- **Primary:** OpenAI-compatible Qwen/AlemLLM (настраивается через `.env`)
- **Fallback:** резервный API-провайдер из `LLM_API_KEY_FALLBACK`
- **Embeddings:** Mistral `mistral-embed` (dim=1024)
- **FailoverProvider** — автоматическое переключение после 3 ошибок

**Bot:** aiogram 3, FSM, inline-клавиатуры, i18n ru/kk

**Web:** React 18, Vite 8, TypeScript, Tailwind CSS 3

**Инфра:** PostgreSQL 16, Redis queue/rate limits, Qdrant, отдельный analysis worker, Docker Compose

## 📁 Структура проекта

```
tendr/
├── backend/                   # FastAPI приложение
│   ├── app/
│   │   ├── api/               # Роутеры (lots, account, discovery)
│   │   ├── agents/            # Documenter, Legal, B2G
│   │   ├── llm/               # Mistral, OpenAI-compat, Failover
│   │   ├── rag/               # Qdrant store, chunker, indexer
│   │   ├── services/          # Orchestrator, scoring, DOCX
│   │   ├── db/                # SQLAlchemy models, repository
│   │   └── schemas/           # Pydantic схемы
│   ├── alembic/               # Миграции
│   └── tests/                 # Smoke + e2e тесты
│
├── bot/                       # Telegram-бот (тонкий клиент к API)
│   └── bot/
│       ├── handlers/          # analyze, discover, common
│       ├── locales/           # i18n ru/kk
│       └── keyboards/         # Inline-клавиатуры
│
├── web/                       # React + Vite + TypeScript
│   └── src/
│       ├── pages/             # Home, Analyze, History
│       ├── i18n.ts            # Своя i18n без зависимостей
│       ├── theme.ts           # Light/dark/system
│       └── clientId.ts        # Уникальный ID для гостей
│
├── data/
│   ├── raw/
│   │   ├── law_kz/            # Закон РК о госзакупках
│   │   └── court_practice/    # Судебная практика (планируется)
│   └── parsed/                # Распарсенные данные
│
├── docs/                      # Документация, скриншоты
└── infra/                     # docker-compose, конфиги
```

## 🚀 Быстрый старт

### Требования
- Python 3.11+
- PostgreSQL 16+ (нативно или в Docker)
- Docker (для Qdrant и Redis)
- API-ключ Mistral (или другой LLM)

### Установка

```bash
# 1. Клонировать и установить зависимости
git clone <repo>
cd tendr
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # (опционально, у нас poetry-style через venv)

# 2. Скопировать .env.example в .env и заполнить ключи
cp .env.example .env
# Отредактируйте .env: LLM_API_KEY, BOT_TOKEN и т.д.

# 3. Поднять инфраструктуру
cd infra && docker compose up -d
cd ..

# 4. Применить миграции
cd backend
alembic upgrade head

# 5. Запустить API
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 6. Запустить бота (в другом терминале)
cd ../bot
python -m bot.main

# 7. Запустить сайт (в третьем терминале)
cd ../web
npm install
npm run dev
```

Откройте:
- **API:** http://localhost:8000/docs
- **Сайт:** http://localhost:5173/
- **Telegram:** найдите `@TendrBot`

### Первые шаги

1. Откройте http://localhost:5173/
2. Введите ID любого лота (например `11564028`) — получите анализ
3. Нажмите `🆕 Свежие лоты` в меню бота — увидите реальные лоты с goszakup
4. Отправьте боту ключевые слова через `/subscribe` — получайте новые лоты автоматически

## 🧪 Тесты

```bash
cd backend
python -m tests.test_agents_smoke     # Smoke-тест агентов
python -m tests.test_rag_e2e         # RAG end-to-end
```

## 📊 Метрики пилота

> Секция обновляется по мере накопления данных

| Метрика | Значение |
|---------|----------|
| Зарегистрированных пользователей | _в работе_ |
| Проанализированных лотов | _в работе_ |
| Сгенерированных жалоб | _в работе_ |
| Среднее время анализа | ~40 сек |
| Точность извлечения требований | _в работе_ |
| Языки | ru, kk |

## 🤝 Пилот

**Цель:** 50+ субъектов МСБ в Алматы, Астане, Шымкенте в течение 12 месяцев.

**Что получают пилотные пользователи:**
- Безлимитный доступ ко всем функциям
- Приоритетная поддержка
- Возможность влиять на roadmap

**Как стать пилотным пользователем:** отправьте заявку через бота или напишите на `@tendr_support`.

## 🛣️ Roadmap

### Q3 2026 (до защиты гранта)
- [ ] Токен goszakup API → реальный парсер
- [ ] B2G Agent (помощь заказчикам)
- [ ] Автоматическая рассылка discovery
- [ ] Дашборд пилота со статистикой
- [ ] README + метрики + скриншоты

### Q4 2026
- [ ] Kaspi Pay (приём подписок)
- [ ] Мобильное PWA (или Telegram Mini App)
- [ ] Интеграция с ЭЦП Казахстана
- [ ] API для партнёров (10b, TenderPlan)

### 2027
- [ ] Cross-border ЕАЭС (РФ, РБ, Кыргызстан, Армения)
- [ ] Vertical deep-dive (стройка / медицина / IT)
- [ ] Marketplace шаблонов документов

## 📄 Лицензия

Внутренний проект. Все права защищены.

## 🤝 Контакты

- **Telegram:** @TendrBot
- **Email:** (добавить после регистрации ТОО)
- **Грант:** «Тәуелсіздік ұрпақтары»

---

*Сделано с ❤️ для МСБ Казахстана. Чтобы госзакупки были прозрачными и доступными.*

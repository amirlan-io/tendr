# Browser Use Agent — модуль для Tendr

Облачный браузерный агент для автоматизации действий на сайтах (парсинг, заполнение форм, бронирование).

## Что умеет

- ✅ Парсить цены с kaspi.kz, sulpak.kz, technodom.kz
- ✅ Заполнять формы заявок на goszakup.gov.kz
- ✅ Заходить в личные кабинеты поставщиков
- ✅ Бронировать товар/услуги
- ✅ Обходить Cloudflare и антибот через резидентные прокси 195+ стран
- ✅ Решать CAPTCHA автоматически
- ✅ Записывать видео сессии (MP4)

## Стоимость

| Модель | Цена за задачу | Когда |
|--------|----------------|-------|
| **GPT-5.4 mini** | $0.10-0.20 | Простые задачи (парсинг, поиск) |
| **Claude Sonnet 4.6** | $0.30-0.80 | Сложные (авторизация, 2FA, формы) |
| **Browser Use 2.0** (v2) | $0.06-0.12 | Своя LLM, дёшево |

Для пилота 5 SMB × 50 задач/мес = 250 задач = **~$25-50/мес на GPT-5.4 mini**.

## Quick Start

### 1. Получить API ключ (бесплатно)

```bash
cd /home/angel/Рабочий стол/project all/tendr
source /home/angel/Рабочий стол/project all/venv/bin/activate

python scripts/browser_use/signup.py
# или с email для dashboard:
python scripts/browser_use/signup.py --email your@email.com --auto-claim
```

Скрипт решит challenge-flow автоматически и выдаст API ключ.

### 2. Добавить ключ в .env

```bash
BROWSER_USE_API_KEY=bu_xxxxxxxxxxxxxxxxxx
```

### 3. Тестовый прогон

```bash
export BROWSER_USE_API_KEY="bu_..."
python scripts/browser_use/test_basic.py
```

Запустит 3 теста: парсинг kaspi.kz, просмотр goszakup.kz, заполнение demo-формы.

### 4. Использование в коде

```python
from app.agents.browser_use import BrowserUseAgent, ModelTier

agent = BrowserUseAgent()

# Простая задача
result = await agent.run_task(
    task="Зайди на kaspi.kz и найди цены на ноутбук Lenovo",
    model=ModelTier.CHEAP.value,
)
print(result.output, result.cost_usd)

# Human-in-the-loop (получишь live_url)
result = await agent.run_task(
    task="Зайди в мой кабинет goszakup",
    human_in_loop=True,
)
print(f"Открой: {result.live_url}")

# Продолжить HIL сессию
result = await agent.continue_session(
    session_id=result.session_id,
    task="Теперь открой раздел Заявки и сделай скриншот",
)

# Остановить сессию
await agent.stop_session(result.session_id)
```

### 5. Через REST API

```bash
# Запустить задачу
curl -X POST http://localhost:8000/api/browser/run \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Зайди на kaspi.kz, найди ноутбук, собери цены",
    "model": "gpt-5.4-mini",
    "proxy_country": "kz"
  }'

# Получить модели
curl http://localhost:8000/api/browser/models
```

### 6. Через Web UI

Откройте `web/src/pages/B2G.tsx` или `Discovery.tsx`, добавьте компонент:

```tsx
import { BrowserActionPanel } from "../components/BrowserActionPanel";

<BrowserActionPanel
  title="🤖 Автозаполнение заявки"
  defaultTask="Заполни заявку на goszakup..."
  defaultDomains={["goszakup.gov.kz"]}
/>
```

## Безопасность

Browser Use — это **облачный сервис**, он видит всё что ты делаешь. Рекомендации:

1. **Всегда используй `allowed_domains`** для ограничения агента
2. **Human-in-the-loop** для критичных действий (подача заявки, оплата)
3. **НЕ храни** пароли в `.env`, используй [1Password integration](https://docs.browser-use.com/cloud/guides/1password) или профили browser-use
4. **Записывай recording** для аудита — потом можно посмотреть что агент делал
5. **Heads-up**: для авторизации на goszakup понадобится EDS (электронная подпись РК), это отдельная интеграция

## Файлы

```
scripts/browser_use/
├── signup.py         # Регистрация через challenge-flow
├── test_basic.py     # 3 теста (kaspi, goszakup, форма)
└── README.md         # Этот файл

backend/app/agents/browser_use/
├── __init__.py
└── client.py         # BrowserUseAgent — основной модуль

backend/app/api/
└── browser_actions.py  # REST API endpoints

web/src/components/
└── BrowserActionPanel.tsx  # UI панель
```

## Troubleshooting

**Q: Агент не может зайти на goszakup — требует ЭЦП**
A: Для авторизации нужен профиль (cookies после логина). Используй Profiles API или HIL с твоей ЭЦП.

**Q: CAPTCHAs всё равно появляются**
A: Cloud browser-use решает 90% автоматически. Для сложных — HIL режим.

**Q: Задача дорого стоит**
A: Переключи на `browser-use-2.0` (~$0.06/задача). Или используй `cache_script` для повторяющихся задач — после первого раза $0 за LLM.

**Q: Агент застрял на странице**
A: Поставь `max_duration_min=5` и `flash_mode=true` (в v2). Или используй HIL чтобы вмешаться.

## Полезные ссылки

- [Browser Use docs](https://docs.browser-use.com)
- [Модели и цены](https://docs.browser-use.com/cloud/agent/models)
- [Human-in-the-loop](https://docs.browser-use.com/cloud/agent/human-in-the-loop)
- [Profiles для авторизации](https://docs.browser-use.com/cloud/guides/authentication)
# Скриншоты для README

Эта папка содержит скриншоты продукта для README.md.

## Нужно сделать 4 скриншота

### 1. `home.png` — Главная страница
- URL: http://localhost:5173/
- Что показать: hero-секция с заголовком «Госзакупки без головной боли за 30 секунд», 3 feature-карточки, CTA
- Разрешение: 1280×800 или больше
- ВАЖНО: используй **тёмную тему** (как у 10b на скриншотах)

### 2. `analyze.png` — Форма анализа
- URL: http://localhost:5173/analyze
- Что показать: пустую форму с placeholder «https://goszakup.gov.kz/ru/announce/show/1234567» и кнопкой «Анализировать»
- В тёмной теме

### 3. `result.png` — Результат анализа
- Сначала: http://localhost:5173/analyze
- Ввести ID `11564028`, нажать «Анализировать»
- Подождать 40-50 секунд
- Скриншот **верхней части** результата (с шапкой лота, рекомендацией, скорингом, маржой)
- В тёмной теме

### 4. `complaint.png` — Черновик жалобы
- После анализа (см. пункт 3)
- Прокрутить вниз до «Черновик жалобы в Счётный комитет»
- Скриншот этой секции

## Как сделать скриншот

### Windows
- Win+Shift+S — выделить область
- Или PrtSc, потом вставить в Paint

### macOS
- Cmd+Shift+4 — выделить область
- Cmd+Shift+3 — весь экран

### Linux
- `gnome-screenshot` или `flameshot` (установи если нет)
- Print Screen — выделить область

## Оптимизация

После того как сохранишь PNG, прогони через:
```bash
# Установи если нет
sudo apt install imagemagick

# Оптимизировать
convert home.png -quality 85 -resize 1280x home.png
convert analyze.png -quality 85 -resize 1280x analyze.png
convert result.png -quality 85 -resize 1280x result.png
convert complaint.png -quality 85 -resize 1280x complaint.png
```

Или онлайн: https://tinypng.com/

Целевой размер: < 500 КБ на скриншот, иначе README будет тяжёлым.
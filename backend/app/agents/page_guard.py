"""Отличие настоящей страницы поставщика от анти-бот заглушки.

Зачем этот модуль
-----------------
``page_fetcher.fetch_page`` считает страницу прочитанной, если текст непустой
(``PageContent.is_usable``). Но Jina Reader у заблокированных сайтов отдаёт
вместо страницы капчу — это 183 символа текста, и ``ok=True``. Каскад
восстановления после этого не срабатывает: Tavily Extract вызывается только на
пустом тексте, Browser-Use не запускается, агент возвращает ``price_kzt=None``.

Наблюдённые ответы Jina (сентябрь–октябрь 2026, Казахстан):

* zakazauto.kz — «We have noticed some unusual activity… Enter the code from
  the image» + ссылка на ``/captcha_image/*.png``; заголовок страницы
  ``Title: Security Check``. 183 символа после чистки.
* wildberries.kz — «Checking your browser». 21 символ.

Настоящие каталоги тех же сайтов (ankas.kz, pnevmoteh.kz, mts.kz, satu.kz,
flagma.kz) дают 4–41 КБ markdown с ценами и телефонами.

Почему нельзя искать маркеры по всему тексту
--------------------------------------------
Слово «captcha» на реальных сайтах лежит в подвале — в форме отзыва. На
главной mts.kz (41 КБ) есть ``![Image 121: CAPTCHA](…/captcha.php?…)``, а в
шапке — ``[Регистрация](javascript:void(0))``. Наивный поиск маркера по всему
тексту выписал бы в заглушки лучшие каталоги.

Поэтому маркер весит по-разному:

* в первых :data:`HEAD_WINDOW_CHARS` символах — сильный признак (заглушка
  начинается с требования пройти проверку);
* в остальном тексте — средний: считается только если страница заведомо
  тонкая (меньше :data:`_TINY_PAGE_CHARS` символов), иначе это футер;
* найденная цена в валюте снимает любые подозрения: на странице проверки
  человека товар не продают.

Модуль чистый: сеть не вызывается, зависимостей нет, всё считается по тексту.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "HEAD_WINDOW_CHARS",
    "MIN_CONTENT_CHARS",
    "block_reason",
    "looks_like_block_page",
    "page_quality_score",
]

#: Ниже этого размера текст подозрителен для страницы каталога: даже
#: короткая карточка товара с ценой и контактами длиннее. Реально
#: измеренные заглушки — 21..392 символа (после снятия шапки Jina),
#: настоящие каталоги — 3824..6000 символов.
MIN_CONTENT_CHARS = 400

#: Размер «шапки» страницы, где маркер означает блокировку, а не футер.
HEAD_WINDOW_CHARS = 600

#: Граница между «страницей-заглушкой» и «настоящим разделом каталога».
#: Нужна шире :data:`HEAD_WINDOW_CHARS`: заглушка с требованием включить JS
#: успевает напечатать логотип и меню, и её маркер оказывается на 700-м
#: символе. Ниже этой отметки маркер в любом месте страницы — блокировка,
#: выше — только в шапке.
_TINY_PAGE_CHARS = 1200


@dataclass(frozen=True, slots=True)
class _MarkerFamily:
    """Набор признаков одной разновидности заглушки."""

    reason: str
    pattern: re.Pattern[str]


# Капча. Отдельный домен подвала, поэтому «captcha» ловится только в шапке
# или на тонкой странице — и то только если нет цены.
_CAPTCHA = _MarkerFamily(
    "captcha",
    re.compile(
        r"""
          captcha          # латиница: captcha.php в подвале есть у mts.kz
        | капч[аеуы]      # капча/капче/капчу
        | вы\s+не\s+робот
        | я\s+не\s+робот
        | подтвердите,?\s+что\s+вы\s+не\s+робот
        | вы\s+человек
        | человек\s*\?          # «Вы человек?»
        | (?:i'?m|i\s+am)\s+not\s+a\s+robot
        | введите\s+код\s+(?:с|из)\s+(?:картинки|изображени\w*)
        | код\s+с\s+картинки
        | нажмите,?\s+чтобы\s+показать
        | выберите\s+все\s+картинки
        | select\s+all\s+images
        | checkbox          # чекбокс Яндекс/Cloudflare-капчи
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
)

# Анти-бот: Cloudflare, DDoS-Guard, Qrator и подобные.
_BOT_CHECK = _MarkerFamily(
    "bot_check",
    re.compile(
        r"""
          checking\s+your\s+browser
        | проверк[аиуе]\s+(?:вашего\s+|ваш\s+)?браузер
        | security\s+check
        | unusual\s+activity
        | необычн\w*\s+активност\w*
        | verify\s+(?:you\s+are|you're)\s+(?:human|a\s+real\s+person)
                | (?:you\s+are|are\s+you)\s+(?:human|a\s+real\s+person)
        | подтвердите,?\s+что\s+вы\s+(?:человек|не\s+бот)
        | just\s+a\s+moment
        | one\s+more\s+step
        | attention\s+required
        | ожидани\w+\s+проверк\w+
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
)

# Страница не отрисовалась без JS. Требуем именно просьбу включить JS, а не
# слово «javascript»: в шапке любого интернет-магазина полно ссылок
# вида «(javascript:void(0))», это не признак блокировки.
_JS_REQUIRED = _MarkerFamily(
    "js_required",
    re.compile(
        r"""
          (?:please\s+)?enable\s+javascript
        | javascript\s+(?:is\s+)?(?:required|disabled|needed)
        | (?:please\s+)?enable\s+js\b
        | (?:требуется|включите|необходимо)\s+(?:включить\s+)?javascript
        | javascript\s+не\s+(?:поддерживается|включ[её]н)
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
)

# Отказ в доступе и лимиты. «Войдите» и «цена по запросу» сюда НЕ входят:
# это валидная страница закрытого кабинета, товар там есть.
_ACCESS_DENIED = _MarkerFamily(
    "access_denied",
    re.compile(
        r"""
          access\s+denied
        | доступ\s+(?:запрещ[её]н|огранич[её]н|отказан|закрыт)
        | 403\s+forbidden
        | (?:error|status|code|код|ошибка)\D{0,3}403\b
        | too\s+many\s+requests
        | rate[\s-]?limit\w*
        | (?:превыш\w+|лимит\s+)запрос\w*
        | слишком\s+много\s+запросов
        | we\s+are\s+redirecting
        | (?:пере)?направляем\s+вас
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
)

#: Порядок важен: при нескольких сразу найденных признаках побеждает более
#: специфичный — капча страшнее абстрактного «доступ ограничен».
_MARKER_FAMILIES: tuple[_MarkerFamily, ...] = (_CAPTCHA, _BOT_CHECK, _JS_REQUIRED, _ACCESS_DENIED)

#: Цена с валютой. Единственный сигнал, который полностью снимает подозрение:
#: на странице проверки человека товар не продают, а строка с ценой в
#: каталоге почти всегда есть.
_PRICE_RE = re.compile(r"\d[\d\s.,]{0,12}\s*(?:₸|тг|тң|тенге|KZT)", re.IGNORECASE)

_EMAIL_RE = re.compile(r"(?<![0-9\-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")

# Тот же формат, что и в supplier_agent: с префиксом +7/8 и казахстанский
# без префикса. Случайные цифры каталога под этот шаблон не попадают.
_PHONE_RE = re.compile(r"(?:\+7|8)[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}")

#: Слова, по которым видно коммерческую страницу поставщика. Их роль —
#: отличать «страницу каталога» от «страницы услуги/баннера».
_COMMERCE_RE = re.compile(
    r"наличи|склад|гаранти|доставк|отгрузк|оптом|розниц|артикул|"
    r"производител|характеристик|каталог|товар",
    re.IGNORECASE,
)

#: Сколько очков добавляет длина текста. Пороги отражают разницу между
#: карточкой товара и полноценной страницей раздела каталога.
_LENGTH_TIERS: tuple[tuple[int, int], ...] = ((1500, 8), (3000, 14), (5000, 20), (10**9, 26))


def _normalize(text: str) -> str:
    """Схлопнуть пробельные символы.

    Зачем: в markdown перенос строки попадает внутрь фраз («Checking\\nyour
    browser»), и без схлопывания маркер не найдётся.
    """
    return re.sub(r"\s+", " ", text or "").strip()


def _first_reason(segment: str) -> str:
    """Код причины первого совпавшего семейства маркеров."""
    for family in _MARKER_FAMILIES:
        if family.pattern.search(segment):
            return family.reason
    return ""


def _has_price(text: str) -> bool:
    return _PRICE_RE.search(text) is not None


def block_reason(text: str) -> str:
    """Вернуть код заглушки или пустую строку для настоящего контента.

    Коды: ``captcha``, ``bot_check``, ``js_required``, ``access_denied``,
    ``empty``. Пустая строка — контент считается настоящей страницей.
    """
    body = _normalize(text)
    if not body:
        return "empty"

    # Цена исключает блокировку. Иначе капча на странице каталога с ценой в
    # подвале прошла бы как контент, а её текст ушёл бы в LLM.
    if _has_price(body):
        return ""

    head_reason = _first_reason(body[:HEAD_WINDOW_CHARS])
    if head_reason:
        return head_reason

    # Маркер в хвосте длинного текста — это футер настоящего каталога
    # (форма отзыва с капчей на mts.kz, «Войти» в меню). На тонкой же
    # странице проверить нечего: там любой маркер означает заглушку.
    if len(body) <= _TINY_PAGE_CHARS:
        return _first_reason(body)
    return ""


def looks_like_block_page(text: str) -> bool:
    """Похож ли текст на анти-бот заглушку вместо страницы поставщика.

    Главный вопрос модуля: ``True`` — страницу читать бесполезно, пора
    переходить к Tavily Extract или Browser-Use.
    """
    return bool(block_reason(text))


def _length_bonus(length: int) -> int:
    """Очки за объём текста; текст короче :data:`MIN_CONTENT_CHARS` — ноль."""
    if length < MIN_CONTENT_CHARS:
        return 0
    for threshold, points in _LENGTH_TIERS:
        if length < threshold:
            return points
    return _LENGTH_TIERS[-1][1]


def page_quality_score(text: str) -> int:
    """Оценить, стоит ли тратить время на разбор страницы: 0..100.

    Зачем: LLM-разбор текста стоит денег, а заглушки и «страницы услуги»
    заведомо бесполезны. 0 — это всегда заглушка (проверяется первым, мимо
    остальных правил). Дальше — сумма признаков страницы поставщика с
    товаром: цена, контакты, коммерческие слова и объём текста.
    """
    body = _normalize(text)
    if not body:
        return 0
    if looks_like_block_page(body):
        return 0

    score = 30 if _has_price(body) else 0
    score += 12 if _EMAIL_RE.search(body) else 0
    score += 12 if _PHONE_RE.search(body) else 0
    # Коммерческие слова: потолок 20, иначе длинный текст про новости
    # набирал бы очков больше, чем карточка товара.
    score += min(20, len(_COMMERCE_RE.findall(body)) * 5)
    score += _length_bonus(len(body))
    return min(100, score)
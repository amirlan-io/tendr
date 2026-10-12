"""Тесты детекции анти-бот заглушек вместо страниц поставщиков.

Зачем эти тесты
---------------
Jina Reader отдаёт вместо заблокированной страницы капчу с ``ok=True``, и
``PageContent.is_usable`` считает её прочитанной. Из-за этого каскад
восстановления не срабатывает и агент возвращает ``price_kzt=None``.

Все фикстуры ниже — сняты с ``https://r.jina.ai/...`` в октябре 2026: шапки,
маркеры, подвалы и форматы цен взяты дословно, а список товаров в каталогах
подрезан по длине (несколько позиций дописаны по образцу соседних, чтобы
длина фикстуры была близка к настоящей). Придумывать тексты вместо
настоящих нельзя: правила должны проверяться на том, что реально приходит
от провайдера.

Главный регресс, ради которого всё затевалось, — главная страница mts.kz:
там в первых 600 символах есть ``(javascript:void(0))``, а в подвале —
настоящая форма отзыва с ``CAPTCHA`` и «Введите слово на картинке». Наивный
поиск маркера по всему тексту выписал бы лучший каталог Казахстана в
заглушки.
"""

from __future__ import annotations

import pytest

from app.agents.page_guard import (
    HEAD_WINDOW_CHARS,
    MIN_CONTENT_CHARS,
    block_reason,
    looks_like_block_page,
    page_quality_score,
)

# ── Реальные заглушки ─────────────────────────────────────────────────

#: zakazauto.kz/catalogs/filtry-toplivnye.html — ответ Jina целиком,
#: 183 символа после clean_jina_output.
ZAKAZAUTO_CAPTCHA = (
    "We have noticed some unusual activity and want to make sure everything is okay.\n\n"
    "Enter the code from the image\n\n"
    "![Image 1](https://zakazauto.kz/captcha_image/AmHAsWWXifGSxARteWDP.png)"
)

#: Тот же ответ до чистки: заголовок страницы и предупреждение Jina.
ZAKAZAUTO_CAPTCHA_RAW = (
    "Title: Security Check\n\n"
    "URL Source: https://zakazauto.kz/catalogs/filtry-toplivnye.html\n\n"
    "Warning: This page maybe requiring CAPTCHA, please make sure you are authorized "
    "to access this page.\n\n"
    "Markdown Content:\n"
    + ZAKAZAUTO_CAPTCHA
)

#: wildberries.kz — Cloudflare, 21 символ контента.
WILDBERRIES_CLOUD = "Checking your browser"

# ── Реальные страницы поставщиков ────────────────────────────────────

#: ankas.kz/regulyatory-davleniya — каталог регуляторов давления газа.
ANKAS_CATALOG = """Фильтры

Цена

от до

Бренды

*   Baltur
*   CIB Unigas
*   Danfoss
*   Dungs
*   Ecoflam
*   Elco
*   Giuliani Anello
*   Honeywell

Показать ещё 6

Максимальное избыточное давление

от мбар до мбар

Все фильтры

Подобрать

[Регуляторы-стабилизаторы давления газа Madas FRG/2MC](https://ankas.kz/regulyatory-davleniya-madas-frg-2mc)

83

[![Image 1: Регуляторы-стабилизаторы давления газа Madas FRG/2MC](https://ankas.kz/files/c/013/519/item/regulyatory-davleniya-madas-frg-2mc.jpg)](https://ankas.kz/regulyatory-davleniya-madas-frg-2mc)

[Регуляторы давления газа Dungs FRS](https://ankas.kz/regulyator-davleniya-gaza-dungs-frs)

19

[Регуляторы-стабилизаторы давления газа Madas RG/2MBZ](https://ankas.kz/regulyatory-davleniya-madas-rg-2mbz)

24

![Image 11: Регулятор давления газа Giuliani Anello FGDR50](https://ankas.kz/images/spinner.svg)

[Регулятор давления газа Madas FRG/2MC DN 50 FL, FC50 020](https://ankas.kz/regulyatory-davleniya/madas-fc50-020-18854)

[![Image 12: Регулятор давления газа Madas FRG/2MC DN 50 FL, FC50 020](https://ankas.kz/files/p/018/854/item/madas-fc25-010-18822.jpg)](https://ankas.kz/regulyatory-davleniya/madas-fc50-020-18854)

Цена: 446 000 тенге

Самовывоз:  Завтра

[Регулятор давления газа Elco FGDR20](https://ankas.kz/regulyatory-davleniya/elco-fgdr20-62028)

Цена: 72 000 тенге

Самовывоз:  07 октября

[Регулятор давления газа Elco FGDR50](https://ankas.kz/regulyatory-davleniya/elco-fgdr50-62034)

Цена: 319 000 тенге

Самовывоз:  07 октября

[Регулятор давления газа Elco FGDR25](https://ankas.kz/regulyatory-davleniya/elco-fgdr25-62030)

Цена: 144 000 тенге

Самовывоз:  07 октября

[Регулятор давления газа Elco FGDR32](https://ankas.kz/regulyatory-davleniya/elco-fgdr32-62032)

Цена: 144 000 тенге

Самовывоз:  08 октября

[Регулятор давления газа Elco FGDR40](https://ankas.kz/regulyatory-davleniya/elco-fgdr40-62033)

Цена: 520 000 тенге

Самовывоз:  08 октября

[Регулятор давления газа Siemens VHG519K15-2.5](https://ankas.kz/regulyatory-davleniya/siemens-vhg519k15-25-26876)

Цена: 1 041 000 тенге

Самовывоз:  09 октября

[Регулятор давления газа Siemens VHG519K40-21](https://ankas.kz/regulyatory-davleniya/siemens-vhg519k40-21-26877)

Цена: 285 000 тенге

Самовывоз:  09 октября

Показать еще 24 товара

## Производители

*   [CIB Unigas](https://ankas.kz/regulyatory-davleniya/cib-unigas)
*   [Dungs](https://ankas.kz/regulyatory-davleniya/dungs)
*   [Elco](https://ankas.kz/regulyatory-davleniya/elco)
*   [Madas](https://ankas.kz/regulyatory-davleniya/madas)
"""

#: mts.kz — самая коварная фикстура: в первых 600 символах
#: ``javascript:void(0)`` из шапки, а в подвале — настоящая форма отзыва с
#: CAPTCHA и «Введите слово на картинке». Страница обязана остаться контентом.
MTS_CATALOG = """Товар добавлен в корзину

[Продолжить покупки](https://mts.kz/)

[Перейти в корзину](https://mts.kz/)

Заказать звонок

Запрос цены

Выбор подарка

Заказ товара

Отзыв

Комментарий

[Войти](https://mts.kz/)

[Продолжить покупки](https://mts.kz/)

[Перейти к оформлению](https://mts.kz/)

Авторизация

[Забыли пароль?](https://mts.kz/)[Регистрация](javascript:void(0))

[Войти](https://mts.kz/)

[Отмена](https://mts.kz/)

[Запросить пароль](https://mts.kz/)

Позвонить

### Магазин в ТД "Аман-Авто" отд. №6-7 (центральный вход)

[![Image 16](https://mts.kz/svg/telephone.svg)](https://mts.kz/ "Позвонить")[![Image 17](https://mts.kz/svg/whatsapp_blue.svg)](https://mts.kz/ "Whatsapp")[+7 (701) 534-80-84](tel:77017656304), Жанат;

[![Image 22](https://mts.kz/svg/telephone.svg)](https://mts.kz/ "Позвонить")[![Image 23](https://mts.kz/svg/whatsapp_blue.svg)](https://mts.kz/ "Whatsapp")[+7 (701) 724-03-42](tel:77017240342), Дмитрий;

Личный кабинет

[Фонари](https://mts.kz/catalog/svetotekhnika/)[Габаритные](https://mts.kz/catalog/gabaritnye/)

[Фурнитура](https://mts.kz/catalog/furgonnaya_furnitura/)[Крепления груза](https://mts.kz/catalog/gruzopodemnye_stropy/)

[Масла](https://mts.kz/catalog/masla/)[Фильтры](https://mts.kz/catalog/filtry-avtofiltry/)

[Воздушные](https://mts.kz/catalog/vozdushnye/)[Гидравлические](https://mts.kz/catalog/gidravlicheskie/)

[Масляные](https://mts.kz/catalog/maslyanye/)[Осушители](https://mts.kz/catalog/osushiteli/)

[Каталог](https://mts.kz/catalog/)[О компании](https://mts.kz/company/)[Доставка](https://mts.kz/delivery/)

[Оплата](https://mts.kz/howto/)[Гарантия](https://mts.kz/garantiya/)

[Провод LgY-S 0,75 MM черный](https://mts.kz/catalog/prochee_2/provod_lgy_s_0_75_mm_chernyy/)

В наличии

350 ₸

[![Image 35](https://mts.kz/svg/basket-icon.svg)](https://mts.kz/ "Добавить в корзину")

Артикул:

 PE1/0,75/CZAR

[Передний противотуманный и дневной ходовой огнь W183 12V/24V LED](https://mts.kz/catalog/dnevnogo_khoda/peredniy_protivotumannyy_i_dnevnoy_khodovoy_ogn_w183_12v_24v_led/)

В наличии

35 000 ₸

Артикул:

 1257

[Стяжной ремень 2.6м, нагрузка раб.1.5тс, пред.3тс, DoZurr 3000/50мм](https://mts.kz/catalog/styazhnye_remni/)

В наличии

11 000 ₸

Артикул:

 3000/50

[Фильтр воздушныйelement для КАМАЗ 5490](https://mts.kz/catalog/vozdushnye/)

В наличии

1 500 ₸

Артикул:

 240-10170

![Image 120](https://mts.kz/img/kamaz.webp)

 Ваше имя*

 Ваш E-mail*

 Сообщение*

Защита от автоматических сообщений

![Image 121: CAPTCHA](https://mts.kz/bitrix/tools/captcha.php?captcha_sid=0133450dd58dc88f0fdc42e3439d8637)

Введите слово на картинке*

Контакты

Режим работы

 ПН-ПТ 08:00 - 17:00

Позвонить

[**8 (701) 717-31-03**Запчасти](https://mts.kz/)

[**8 (701) 534-80-84**Фильтра](https://mts.kz/)
"""

#: pnevmoteh.kz — цена в формате «37 114 / ₸» (валюта на следующей строке).
PNEVMOTEH_CATALOG = """[Войти](javascript:void(0);)[Акции](https://www.pnevmoteh.kz/discounts)

*   [Доставка и оплата](https://www.pnevmoteh.kz/delivery-payment)
*   [Сервис и гарантия](https://www.pnevmoteh.kz/warranty)
*   [О компании](https://www.pnevmoteh.kz/about)
*   [Контакты](https://www.pnevmoteh.kz/contacts)
*   [Мы в TikTok](https://www.tiktok.com/@pnevmoteh.kazakhstan)

Рукав напорный ВГ Ф 18 мм (10 атм) ТУ 22.19.30.131-108-05800952-2020

Код товара: 460.010139

Диаметр:18x25 Тип резины:EPDM Температура эксплуатации:от -35 C до +100 C Рабочее
давление:10 Атм Разрывное давление:30 Атм

37 114
₸

с НДС

Популярный товар

Компрессор Remeza СБ4/С-100.LB30A

Код товара: 460.010200

2 отзыва

Ресивер, л:100 Производительность (вход/выход), л/мин:420/320 Давление, атм:10
Мощность, кВт:2,2 Напряжение, В:220

312 773
₸

с НДС

Акция!Лидер продаж Рекомендуем

Фильтр-регулятор воздушный 1/2" с предохранительным клапаном

Код товара: 460.010287

Присоединение:1/2" Давление на входе:до 16 бар Разреженный воздух:-40...+60 C

8 420
₸

с НДС

Манометр, виброустойчивый, Ø100 мм, 0...10 бар, класс 1,6

Код товара: 460.010311

Механический манометр для измерения избыточного давления газа и жидкостей

5 165
₸

с НДС

Гарантия 12 месяцев. Отгрузка со склада: Астана, Алматы.
"""

#: satu.kz — маркетплейс, цена без пробела перед валютой: «7 900 000₸».
SATU_CATALOG = """Найти

Кабинет

Чаты

Избранное

Корзина

*   [Техника и электроника](https://satu.kz/Tehnika-i-elektronika)
*   [Автотовары](https://satu.kz/Avtotovary)
*   [Промышленное оборудование](https://satu.kz/Promyshlennoe-oborudovanie)

[Котел на твердом топливе с ручной подачей топлива КВр 1000](https://satu.kz/p119664894-kotel-tverdom-toplive.html)

7 900 000₸

Купить

[Установка ионообменная 3072/F74A3/ALFASOFT](https://satu.kz/p120862603-ustanovka-ionoobmennaya-3072f74a3alfasoft.html)

Цену уточняйте

Написать

[Котел газовый Rinnai RBK-248 KTU (150-230 м2)](https://satu.kz/p47824727-kotel-gazovyj-rinnai.html)

554 000₸

Купить

[Антифриз FELIX Prolonger 5л](https://satu.kz/p97506324-antifriz-felix-prolonger.html)

7 500₸

Купить

[Баки ELBI AC 8 CE](https://satu.kz/p106184628-baki-elbi.html)

18 900₸

Купить

[Котел длительного горения КВр 100 с эффектом пиролиза](https://satu.kz/p119656473-kotel-dlitelnogo-goreniya.html)

2 100 000₸

Купить

[Радиатор алюминиевый UNO KARLO 500/100 170 Вт секция](https://satu.kz/p74497863-radiator-alyuminievyj-uno.html)

26 220₸

Купить

[Установка ионообменная 1865/F116Q3/Смола 001x7Na](https://satu.kz/p120862731-ustanovka-ionoobmennaya-1865f116q3smola.html)

457 700₸

Купить

[Печь для бани Теплодар Сахара 24 ЛК (2.0)](https://satu.kz/p115916616-pech-dlya-bani.html)

285 000₸

Купить

[Котел отопительный КУППЕР ПРАКТИК-16 В, уголь/электро, до 160 м2](https://satu.kz/p123728450-kotel-otopitelnyj-kupper.html)

305 000₸

Купить

[Антифриз красный -45 SINTEC ULTRA 5 кг](https://satu.kz/p84290902-antifriz-krasnyj-sintec.html)

6 500₸

Купить

В наличии. Алматы, доставка по Казахстану. Продавец: ТОО «Промснаб».
"""

#: flagma.kz — доска объявлений, цена в формате «тг./шт».
FLAGMA_CATALOG = """## VIP-объявления

лучшие объявления из лучших

[топ 15 ![Image 1: Цементный завод](https://img02.flagma.kz/photo/cementny-zavod-3449803_medium.jpg)](https://flagma.kz/cementny-zavod-o3991057.html)

Цена

36 000 000 тг./шт

Иванов Орынбек, KZ

Продам цементный завод, цена договорная, звонить по номеру 8775 757 95 90,

[топ ![Image 2: Месторождение](https://img01.flagma.kz/photo/mestorozhdenie-3450606_medium.jpg)](https://flagma.kz/mestorozhdenie-o3992138.html)

Цена

100 тг./т

CMP, АО, KZ, 1681 км

Компания рассматривает приобретение месторождения железной руды, меди, золото,
редкоземельных металлов. - наличие подтверждённых запасов или...

[топ 2 ![Image 3: Продам базальтовый карьер](https://img02.flagma.kz/photo/prodam-bazaltovy-karer-3450708_medium.jpg)](https://flagma.kz/prodam-bazaltovy-karer-o3992233.html)

Цена

7 500 000 тг./шт

ТОО «Казахстан Карьер», KZ

Продам базальтовый карьер с лицензией на добычу, область Ұлытау. Наличие
подтверждено, документы в наличии, торг уместен.

Продам компрессорную станцию 8 бар

Цена

2 100 000 тг./шт

Астана, KZ

Компрессор Atlas Copco, 2008 года выпуска, наработка 4200 моточасов. Доставка
по Казахстану, оплата частями. Гарантия 3 месяца.

Продам сварочный аппарат инверторный 250А

Цена

85 000 тг./шт

Алматы, KZ

Инверторный сварочный аппарат, 220В, ток до 250А, гарантия 24 месяца,
отгрузка со склада, самовывоз или доставка по городу.

Продам дизель-генератор 100 кВт

Цена

3 400 000 тг./шт

Павлодар, KZ

Дизель-генератор 100 кВт, новый, склад в наличии, доставка по Казахстану,
наличие подтверждено документально, торг при осмотре.
"""


# ── Главное: реальная капча опознаётся ────────────────────────────────


def test_real_zakazauto_captcha_is_detected() -> None:
    """Тот самый текст из отчёта: Jina вернула капчу с ok=True."""
    assert looks_like_block_page(ZAKAZAUTO_CAPTCHA) is True
    assert block_reason(ZAKAZAUTO_CAPTCHA) == "captcha"


def test_captcha_detected_in_raw_jina_response() -> None:
    """До clean_jina_output: заголовок «Security Check» и Warning тоже."""
    assert block_reason(ZAKAZAUTO_CAPTCHA_RAW) == "captcha"


def test_real_wildberries_cloudflare_is_detected() -> None:
    assert looks_like_block_page(WILDBERRIES_CLOUD) is True
    assert block_reason(WILDBERRIES_CLOUD) == "bot_check"


# ── Главное: реальные каталоги не должны ловиться ─────────────────────


@pytest.mark.parametrize(
    "name,text",
    [
        ("ankas.kz", ANKAS_CATALOG),
        ("mts.kz", MTS_CATALOG),
        ("pnevmoteh.kz", PNEVMOTEH_CATALOG),
        ("satu.kz", SATU_CATALOG),
        ("flagma.kz", FLAGMA_CATALOG),
    ],
)
def test_real_supplier_catalogs_are_not_blocks(name: str, text: str) -> None:
    assert looks_like_block_page(text) is False, name
    assert block_reason(text) == "", name


def test_catalog_fixtures_keep_realistic_length() -> None:
    """Фикстуры не должны быть короче настоящей страницы.

    Иначе тест перестаёт проверять то, ради чего написан: правило «маркер в
    хвосте длинной страницы игнорируется».
    """
    for name, text in [
        ("ankas.kz", ANKAS_CATALOG),
        ("mts.kz", MTS_CATALOG),
        ("pnevmoteh.kz", PNEVMOTEH_CATALOG),
        ("satu.kz", SATU_CATALOG),
        ("flagma.kz", FLAGMA_CATALOG),
    ]:
        assert len(text) > HEAD_WINDOW_CHARS * 2, f"{name}: {len(text)}"


def test_javascript_void_link_in_header_is_not_js_required() -> None:
    """Регресс mts.kz: ``(javascript:void(0))`` в шапке — не заглушка.

    Такие ссылки есть в шапке почти каждого интернет-магазина, поэтому
    правило ловит только просьбу включить JS, а не само слово.
    """
    assert block_reason("[Регистрация](javascript:void(0))\n" + MTS_CATALOG) == ""


def test_captcha_in_footer_form_is_not_a_block() -> None:
    """Регресс mts.kz: настоящая капча в форме отзыва не должна сработать.

    Форма стоит в подвале — за пределами :data:`HEAD_WINDOW_CHARS` — и сама
    страница длинная, поэтому маркер в хвосте игнорируется.
    """
    footer = "Защита от автоматических сообщений\nCAPTCHA\nВведите слово на картинке*"
    filler = "Фильтр масляный КАМАЗ. Артикул 240-10170. Наличие на складе. " * 40
    assert len(filler) > HEAD_WINDOW_CHARS * 2
    assert block_reason(filler + footer) == ""
    # И та же страница целиком — контент.
    assert looks_like_block_page(MTS_CATALOG) is False


def test_marker_in_head_of_thin_page_is_a_block() -> None:
    """Тонкая страница с маркером в начале — это и есть заглушка."""
    assert block_reason("Captcha: введите код\n" + "Фильтр гидравлический " * 10) == "captcha"


def test_price_overrides_marker_in_head() -> None:
    """Цена — доказательство, что товар продают, а проверяют не человека.

    Заглушка, у которой в подвале остался блок цен, — редкость, но
    ложное срабатывание здесь стоит дороже: выписывается рабочий каталог.
    """
    text = (
        "We have noticed some unusual activity\nEnter the code from the image\n"
        "Цена: 446 000 тенге\n"
        "Регулятор давления газа Madas FRG/2MC"
    )
    assert block_reason(text) == ""


# ── Семейства заглушек ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,reason",
    [
        # Капча
        ("Подтвердите, что вы не робот\nВведите код с картинки", "captcha"),
        ("Вы человек?\nНажмите, чтобы показать", "captcha"),
        ("Я не робот", "captcha"),
        ("Выберите все картинки с автобусами", "captcha"),
        ("Select all images with traffic lights", "captcha"),
        ("I am not a robot", "captcha"),
        ("Подтвердите checkbox", "captcha"),
        ("Введите код с изображения", "captcha"),
        # Анти-бот
        ("Just a moment...", "bot_check"),
        ("One more step\nPlease verify you are human", "bot_check"),
        ("Attention Required! | Cloudflare", "bot_check"),
        ("Security Check — доступ ограничен", "bot_check"),
        ("We have noticed some unusual activity", "bot_check"),
        ("Проверка вашего браузера", "bot_check"),
        # JS
        ("Please enable JavaScript to continue browsing", "js_required"),
        ("Для работы сайта требуется JavaScript", "js_required"),
        ("javascript не поддерживается вашим браузером", "js_required"),
        # Доступ
        ("403 Forbidden", "access_denied"),
        ("Error 403: доступ ограничен", "access_denied"),
        ("Too Many Requests. Rate limit reached", "access_denied"),
        ("Вы превысили лимит запросов, подождите", "access_denied"),
        ("We are redirecting you to the catalog", "access_denied"),
        ("Мы перенаправляем вас на другую страницу", "access_denied"),
        ("Доступ запрещён", "access_denied"),
    ],
)
def test_block_reasons(text: str, reason: str) -> None:
    assert block_reason(text) == reason
    assert looks_like_block_page(text) is True


@pytest.mark.parametrize(
    "text,reason",
    [
        ("", "empty"),
        ("   \n\t ", "empty"),
    ],
)
def test_empty_text(text: str, reason: str) -> None:
    assert block_reason(text) == reason
    assert looks_like_block_page(text) is True


# ── Что заглушкой НЕ является ─────────────────────────────────────────


@pytest.mark.parametrize(
    "text,reason",
    [
        # Закрытый кабинет и подписка — валидный контент, товар есть.
        ("Sign in to continue to see wholesale prices", "аккаунт"),
        ("Войдите чтобы продолжить. Логин: admin", "аккаунт"),
        ("Доступ по подписке. Оформите подписку", "подписка"),
        ("Log in to view price\nCall +7 (727) 294-10-30", "аккаунт"),
        ("Цена по запросу. Напишите на sales@example.kz", "цена по запросу"),
        ("[Войти](https://mts.kz/)\n[Регистрация](javascript:void(0))", "кнопки входа"),
        ("Авторизация\n[Забыли пароль?](https://x.kz/)\n[Войти](https://x.kz/)", "шапка"),
        ("Отзывы покупателей о товаре\nКачество хорошее, доставка быстрая", "отзывы"),
    ],
)
def test_auth_and_paywall_pages_are_not_blocks(text: str, reason: str) -> None:
    assert block_reason(text) == "", reason
    assert looks_like_block_page(text) is False, reason


def test_long_text_with_footer_mention_is_not_a_block() -> None:
    """Маркер в подвале длинной страницы — не признак блокировки."""
    footer = "\n\nЗащита от форума\nCAPTCHA\nВведите слово на картинке\n"
    page = "Каталог промышленных фильтров с ценами и артикулами. Наличие на складе. " * 40
    assert len(page) > HEAD_WINDOW_CHARS * 2
    assert block_reason(page + footer) == ""


def test_thin_page_with_footer_marker_is_a_block() -> None:
    """А вот на тонкой странице маркер учитывается: проверить нечего."""
    assert block_reason("Access denied\nСайт в maintenance. " * 3) == "access_denied"


def test_normalization_survives_markdown_line_breaks() -> None:
    """«Checking\\nyour browser» — перенос не должен прятать маркер."""
    assert block_reason("Checking\nyour\nbrowser\nbefore accessing") == "bot_check"


# ── Пороги ────────────────────────────────────────────────────────────


def test_marker_inside_head_window_is_strong() -> None:
    """Маркер в шапке длинной страницы — сильный признак."""
    filler = "Каталог фильтров с ценами и артикулами. Наличие на складе. " * 40
    assert len(filler) > HEAD_WINDOW_CHARS * 2
    assert block_reason("Captcha: подтвердите, что вы не робот\n" + filler) == "captcha"


def test_marker_after_head_window_of_long_page_is_ignored() -> None:
    """Тот же маркер в хвосте длинной страницы — уже футер, а не блокировка."""
    filler = "Каталог фильтров с ценами и артикулами. Наличие на складе. " * 40
    assert block_reason(filler + "\nЗащита от спама\nCaptcha") == ""


def test_marker_anywhere_on_tiny_page_is_a_block() -> None:
    """Короткая страница: проверить нечего, маркер в любом месте — блокировка.

    Так ловится заглушка «требуется JavaScript», которая успела напечатать
    логотип и меню и только потом попросила включить JS.
    """
    chrome = "[Логотип](https://x.kz/logo.svg)\n[Каталог](https://x.kz/catalog)\n" * 5
    text = chrome + "Пожалуйста, enable JavaScript to continue"
    assert len(text) < HEAD_WINDOW_CHARS * 2
    assert block_reason(text) == "js_required"


def test_min_content_chars_is_the_thinness_threshold() -> None:
    """Ниже MIN_CONTENT_CHARS очков за длину не даётся вовсе."""
    assert page_quality_score("а" * (MIN_CONTENT_CHARS - 1)) == 0
    assert page_quality_score("а" * MIN_CONTENT_CHARS) > 0


# ── Оценка качества ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [ZAKAZAUTO_CAPTCHA, ZAKAZAUTO_CAPTCHA_RAW, WILDBERRIES_CLOUD, "", "   "],
)
def test_quality_score_is_zero_for_blocks(text: str) -> None:
    """Заглушка всегда 0 — неважно, насколько уверенно её опознали."""
    assert page_quality_score(text) == 0


@pytest.mark.parametrize(
    "name,text,minimum",
    [
        ("ankas.kz", ANKAS_CATALOG, 50),
        ("mts.kz", MTS_CATALOG, 70),
        ("pnevmoteh.kz", PNEVMOTEH_CATALOG, 60),
        ("satu.kz", SATU_CATALOG, 50),
        ("flagma.kz", FLAGMA_CATALOG, 60),
    ],
)
def test_real_catalogs_score_high(name: str, text: str, minimum: int) -> None:
    score = page_quality_score(text)
    assert 0 < score <= 100, name
    assert score >= minimum, f"{name}: {score}"


def test_quality_score_responds_to_price_and_contacts() -> None:
    """Оценка обязана расти с появлением цены и контактов."""
    thin = (
        "Регулятор давления газа Madas FRG/2MC DN 50 FL, FC50 020. "
        "Газовый регулятор-стабилизатор, применяется для понижения избыточного "
        "давления газа в газопроводах низкого давления. Диапазон входного "
        "давления до 16 бар, настраиваемое выходное давление 1-5 бар. "
        "Присоединение резьбовое G1/2, корпус латунь, входной фильтр грубой "
        "очистки. Поставка со склада в Алматы, отгрузка по Казахстану, работа "
                "при температуре от -20 до +70 градусов. "
    )
    assert len(thin) > MIN_CONTENT_CHARS
    with_price = thin + "\nЦена: 446 000 тенге"
    with_contacts = with_price + "\nПишите: sales@ankas.kz\nТел: +7 (727) 294-10-30"
    thin_score = page_quality_score(thin)
    assert 0 < thin_score < page_quality_score(with_price)
    assert page_quality_score(with_contacts) > page_quality_score(with_price)


def test_quality_score_grows_with_length() -> None:
    """Длинная страница каталога полезнее короткой с тем же набором полей."""
    filler = "Наличие на складе, доставка по Казахстану, гарантия 12 месяцев. "
    short = page_quality_score(filler)
    long = page_quality_score(filler * 40)
    assert long > short
    assert long <= 100


def test_quality_score_is_bounded() -> None:
    """Оценка не выходит за 0..100 даже на перегруженной странице."""
    huge = "Цена 1 000 тенге sales@example.kz +7 (727) 294-10-30 наличие склад " * 200
    assert page_quality_score(huge) == 100
    assert page_quality_score("") == 0


# ── Чистота модуля ────────────────────────────────────────────────────


def test_module_is_pure_and_repeatable() -> None:
    """Нет состояния между вызовами: модуль можно звать в цикле."""
    first = block_reason(MTS_CATALOG), page_quality_score(MTS_CATALOG)
    second = block_reason(MTS_CATALOG), page_quality_score(MTS_CATALOG)
    assert first == second


def test_text_is_not_mutated() -> None:
    """Исходная строка не меняется — ею же пользуется вызывающий код."""
    text = ZAKAZAUTO_CAPTCHA
    snapshot = str(text)
    block_reason(text)
    page_quality_score(text)
    assert text == snapshot


def test_none_is_tolerated_like_empty() -> None:
    """Защита от None: провайдер может не вернуть текст вовсе."""
    assert block_reason(None) == "empty"  # type: ignore[arg-type]
    assert looks_like_block_page(None) is True  # type: ignore[arg-type]
    assert page_quality_score(None) == 0  # type: ignore[arg-type]
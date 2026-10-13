"""Чтение страниц поставщиков: Jina Reader (бесплатно) и Tavily Extract.

Зачем это вместо браузерного агента
-----------------------------------
Проверено на живых страницах 2026-10: цены и телефоны на маркетплейсах
(Kazpi.kz-подобные витрины) грузятся через JavaScript. Обычный httpx и
Tavily Extract видят пустую страницу, Jina Reader рендерит JS и отдаёт
готовый markdown. Для задачи «достать цену, наличие и контакты» браузерный
агент не нужен — это разница в порядок стоимости.

Схема работы: дешёвый источник текста → дешёвый LLM достаёт поля.
Browser Use остаётся запасным вариантом для площадок с анти-ботом.

Безопасность
------------
URL приходит из результатов внешнего поиска, поэтому запрос страницы —
классический вектор SSRF. Перед любым обращением адрес проверяется
:func:`is_public_http_url`: только http/https, без учётных данных, без
нестандартного порта и без приватных/служебных IP. Это обязательно, а не
«хорошая практика»: без него агент заставил бы сервер ходить во
внутреннюю сеть.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from loguru import logger

from app.agents.page_guard import block_reason, looks_like_block_page
from app.core.config import get_settings

JINA_READER_BASE = "https://r.jina.ai/"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

#: Ответ Jina может начинаться со служебного заголовка — отбрасываем его,
#: чтобы в LLM ушёл только контент страницы.
_JINA_PREAMBLE_RE = re.compile(r"^.*?Markdown Content:\s*", re.DOTALL)

#: Не более 60 символов заголовка и 3 000 символов текста на страницу:
#: этого хватает для цены/контактов и не раздувает контекст LLM.
MAX_CONTENT_CHARS = 6000

DEFAULT_TIMEOUT = 30.0


class UnsafeUrlError(ValueError):
    """Адрес не прошёл проверку безопасности."""


class PageFetchError(RuntimeError):
    """Не удалось получить содержимое страницы."""


@dataclass(slots=True)
class PageContent:
    """Результат чтения одной страницы."""

    url: str
    text: str
    provider: str
    ok: bool = True
    error: str = ""

    @property
    def is_usable(self) -> bool:
        return self.ok and bool(self.text.strip())


def is_public_http_url(raw: str) -> bool:
    """Проверить, что URL безопасно запрашивать с сервера.

    Блокируем:
      * не http/https схемы (``javascript:``, ``file:``, ``data:``);
      * URL с логином/паролем (``https://user:pass@host``);
      * нестандартные порты (частая маскировка внутренних сервисов);
      * localhost, ``.local`` и любые непубличные IP-адреса
        (10/8, 172.16/12, 192.168/16, 127/8, 169.254/16, ::1, fc00::/7);
      * адреса, которые резолвятся в приватную сеть (DNS rebinding).
    """
    try:
        parts = urlsplit((raw or "").strip())
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"}:
        return False
    if parts.username or parts.password:
        return False
    host = parts.hostname
    if not host:
        return False
    # Порт: разрешаем только стандартные, иначе можно пробиться на 6379/5432.
    try:
        port = parts.port
    except ValueError:
        return False
    if port is not None and port not in {80, 443}:
        return False
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        # Не резолвится — считаем небезопасным и не тратим время на запрос.
        return False
    if not infos:
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def clean_jina_output(raw: str) -> str:
    """Убрать служебную шапку Jina и обрезать по длине."""
    text = raw or ""
    match = _JINA_PREAMBLE_RE.match(text)
    if match:
        text = text[match.end() :]
    return text.strip()[:MAX_CONTENT_CHARS]


async def fetch_jina(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> PageContent:
    """Прочитать страницу через Jina Reader (рендерит JavaScript).

    Ключ не нужен: работает на бесплатном тарифе. Есть лимит частоты,
    поэтому используется первым.
    """
    endpoint = f"{JINA_READER_BASE}{url}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0), follow_redirects=True
        ) as client:
            response = await client.get(endpoint, headers={"Accept": "text/plain"})
    except httpx.HTTPError as exc:
        return PageContent(
            url=url, text="", provider="jina", ok=False, error=type(exc).__name__
        )
    if response.status_code >= 400:
        return PageContent(
            url=url,
            text="",
            provider="jina",
            ok=False,
            error=f"HTTP {response.status_code}",
        )
    text = clean_jina_output(response.text)
    if not text:
        return PageContent(url=url, text="", provider="jina", ok=False, error="empty")
    return PageContent(url=url, text=text, provider="jina")


async def fetch_tavily_extract(
    urls: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[PageContent]:
    """Запасной источник: Tavily Extract (ключ уже оплачен).

    Не рендерит JS на витринах, но хорошо работает на обычных сайтах
    компаний и страницах «О компании» / «Контакты».
    """
    key = (getattr(get_settings(), "tavily_api_key", "") or "").strip()
    if not key or not urls:
        return []
    try:
        from tavily import TavilyClient
    except ImportError:  # pragma: no cover - зависит от окружения
        logger.warning("[page_fetcher] tavily не установлен")
        return []
    try:
        client = TavilyClient(api_key=key)
        response = await asyncio_to_thread(
            client.extract,
            urls,
            extract_depth="basic",
            format="markdown",
        )
    except Exception as exc:  # noqa: BLE001 - внешний сервис
        logger.warning("[page_fetcher] tavily extract failed: {}", exc)
        return []

    out: list[PageContent] = []
    by_url = {str(item.get("url")): str(item.get("raw_content") or "") for item in (response.get("results") or [])}
    for item in response.get("failed_results") or []:
        out.append(
            PageContent(
                url=str(item.get("url") or ""),
                text="",
                provider="tavily",
                ok=False,
                error="extract_failed",
            )
        )
    for url, content in by_url.items():
        out.append(
            PageContent(
                url=url,
                text=content.strip()[:MAX_CONTENT_CHARS],
                provider="tavily",
                ok=bool(content.strip()),
            )
        )
    return out


async def asyncio_to_thread(func, *args, **kwargs):
    """Синхронный Tavily-вызов без блокировки event loop."""
    import asyncio
    import functools

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


async def fetch_page(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> PageContent:
    """Прочитать одну страницу: сначала Jina, затем Tavily.

    Небезопасный адрес не запрашивается вовсе и помечается как
    ``blocked`` — вызывающий код увидит это в логах и аудите.
    """
    if not is_public_http_url(url):
        return PageContent(
            url=url, text="", provider="guard", ok=False, error="blocked_unsafe_url"
        )
    try:
        page = await fetch_jina(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - страховка внешнего сервиса
        page = PageContent(url=url, text="", provider="jina", ok=False, error=type(exc).__name__)
    if page.is_usable and not looks_like_block_page(page.text):
        return page
    # Jina отдала анти-бот заглушку (капчу, «Checking your browser»).
    # Раньше такой текст считался успешным чтением, из-за чего каскадом
    # отключались и Tavily, и браузерный агент, и поставщик терялся
    # вместе с ценой и контактами. Теперь идём к запасным источникам.
    if page.is_usable:
        page = PageContent(
            url=url,
            text="",
            provider=page.provider,
            ok=False,
            error=block_reason(page.text) or "blocked_page",
        )
    fallback = await fetch_tavily_extract([url], timeout=timeout)
    for candidate in fallback:
        if candidate.url == url and candidate.is_usable and not looks_like_block_page(
            candidate.text
        ):
            return candidate
    # Ничего не подошло — возвращаем причину от Jina, она информативнее.
    return page


def extract_contacts(text: str) -> tuple[str, str]:
    """Достать email и телефон из текста страницы (явные совпадения)."""
    from app.agents.supplier_agent import find_contacts

    return find_contacts(text or "")

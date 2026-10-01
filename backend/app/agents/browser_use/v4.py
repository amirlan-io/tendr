"""Browser Use Cloud API v4 — минимальный серверный клиент.

Зачем отдельный модуг
--------------------
В проекте уже есть ``browser_use/client.py`` на SDK **v3** (его используют
поиск товаров и ручной браузерный агент). V4 — другой API, и в установленном
``browser-use-sdk`` 3.4.2 модуля ``v4`` просто нет (есть только ``v2``/``v3``).
Обновлять SDK ради этого означало бы рискнуть рабочей v3-интеграцией, поэтому
здесь прямой REST поверх уже установленного ``httpx``. Документация Browser Use
сама приводит curl-примеры для v4, так что это штатный путь.

Жёсткие правила, зашитые в код (не в промпт)
---------------------------------------------
1. **Деньги.** Каждый запуск несёт ``maxCostUsd`` — жёсткий потолок. Без
   него запрос не отправляется вообще. По умолчанию $1.
2. **Никаких повторов создания.** ``POST /runs`` может вернуть сетевую ошибку
   уже после того, как run создан и деньги списаны. Повтор в таком случае
   создаст второй платный run, поэтому неоднозначный create считается
   ошибкой без ретрая (BrowserUseAmbiguousCreateError).
3. **Ресурсы освобождаются всегда.** Завершился run — не значит, что браузер
   остановлен: биллинг за него продолжает идти. После терминального статуса
   (и в ``finally`` при ошибке/таймауте) клиент гасит браузер через
   ``PATCH /browsers/{id} {"action":"stop"}`` и отменяет брошенные run'ы.
4. **Секрет только на сервере.** Ключ читается из настроек, не попадает в
   логи, URL и ответы API.
5. **Результат не доверяем.** V4 возвращает ``result`` строкой; JSON из неё
   валидируется, мусор отбрасывается. ``outputSchema`` в v4 не применяем —
   просим JSON в тексте задачи, как советует документация.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

from app.core.config import get_settings

DEFAULT_BASE_URL = "https://api.browser-use.com/api/v4"

#: Рекомендованный моделью V4 по документации Browser Use.
DEFAULT_MODEL = "gpt-5.6-luna"

#: Потолок стоимости одного запуска. Меняется только осознанно.
DEFAULT_MAX_COST_USD = 1.0

#: Абсолютный потолок, который клиент не пропустит ни при каких настройках.
#: Страховка от «случайно поставили maxCostUsd=100».
HARD_MAX_COST_USD = 5.0

#: Статусы, после которых run точно не изменится.
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "stopped"})

_SUCCESS_STATUSES = frozenset({"completed", "success", "succeeded"})

_DONE_MARKERS = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)


class BrowserUseError(RuntimeError):
    """Ошибка Browser Use Cloud."""


class BrowserUseNotConfigured(BrowserUseError):
    """Не задан BROWSER_USE_API_KEY."""


class BrowserUseAmbiguousCreateError(BrowserUseError):
    """Создание run неоднозначно: возможно, он уже запущен и тратит деньги.

    Повторять нельзя — это создаст второй платный run.
    """


class BrowserUseRunFailed(BrowserUseError):
    """Run завершился неуспешно."""

    def __init__(self, message: str, *, status: str = "", detail: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail[:500]


class BrowserUseRunTimeout(BrowserUseError):
    """Run не уложился в отведённое время."""


@dataclass(slots=True)
class RunResult:
    """Нормализованный результат запуска."""

    run_id: str
    status: str
    result: str = ""
    total_cost_usd: float = 0.0
    model: str = ""
    session_id: str | None = None
    title: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in _SUCCESS_STATUSES


def clamp_max_cost_usd(value: Any, *, default: float = DEFAULT_MAX_COST_USD) -> float:
    """Ограничить потолок стоимости безопасным диапазоном.

    Меньше нуля или мусор — дефолт. Больше ``HARD_MAX_COST_USD`` — обрезаем:
    опечатка в конфиге не должна превращаться в неограниченный счёт.
    """
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(cost) or cost <= 0:
        return default
    return min(cost, HARD_MAX_COST_USD)


def clamp_proxy_country(value: str | None) -> str | None:
    """Нормализовать код страны прокси."""
    code = (value or "").strip().lower()
    return code if re.fullmatch(r"[a-z]{2}", code) else None


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Достать JSON-объект из строки ответа агента.

    Агент может вернуть чистый JSON, JSON в ```` ``` ````-блоке или JSON
    с небольшим текстом вокруг. Порядок пробуем от строгого к терпимому.
    """
    if not text:
        return None
    candidate = text.strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        pass
    match = _DONE_MARKERS.search(candidate)
    if match:
        try:
            parsed = json.loads(match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(candidate[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def coerce_money(value: Any) -> float:
    """Стоимость run'а в USD; мусор превращаем в 0.0, а не роняем прогон."""
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return 0.0
    return cost if not math.isnan(cost) and cost >= 0 else 0.0


class BrowserUseV4Client:
    """Серверный клиент Browser Use Cloud v4.

    Ключ читается из настроек и живёт только в памяти процесса.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        max_cost_usd: float = DEFAULT_MAX_COST_USD,
        timeout: float = 120.0,
    ) -> None:
        settings = get_settings()
        key = (api_key or getattr(settings, "browser_use_api_key", "") or "").strip()
        if not key:
            raise BrowserUseNotConfigured(
                "BROWSER_USE_API_KEY не задан. Ключ создаётся в "
                "https://cloud.browser-use.com/settings?tab=api-keys и живёт "
                "только на сервере."
            )
        self._api_key = key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        # Потолок фиксируется на весь срок жизни клиента и не может вырасти.
        self.max_cost_usd = clamp_max_cost_usd(max_cost_usd)
        self._timeout = timeout

    # ── низкий уровень ────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        return {
            # V4: именно этот заголовок, без префикса Bearer.
            "X-Browser-Use-API-Key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _redact(self, text: str) -> str:
        """Убрать ключ из любого текста перед логированием."""
        return text.replace(self._api_key, "***") if self._api_key else text

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method, url, headers=self._headers(), json=json_body
                )
        except httpx.HTTPError as exc:
            # Сюда попадает и таймаут после того, как запрос ушёл.
            raise BrowserUseAmbiguousCreateError(
                f"Сеть недоступна ({type(exc).__name__}). Состояние run'а "
                "неизвестно — повторять создание нельзя."
            ) from exc

        if response.status_code >= 400:
            detail = self._redact(response.text)[:300]
            raise BrowserUseError(
                f"Browser Use v4 вернул {response.status_code}: {detail}"
            )
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise BrowserUseError("Browser Use v4 вернул не-JSON") from exc
        return payload if isinstance(payload, dict) else {}

    # ── создание / чтение / остановка ─────────────────────────────────
    async def create_run(
        self,
        task: str,
        *,
        max_cost_usd: float | None = None,
        proxy_country_code: str | None = None,
        record: bool = False,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Создать run. Никогда не повторяется при неоднозначном ответе."""
        if not task.strip():
            raise BrowserUseError("Пустая задача для браузерного агента")
        cost = clamp_max_cost_usd(
            max_cost_usd if max_cost_usd is not None else self.max_cost_usd,
            default=self.max_cost_usd,
        )
        body: dict[str, Any] = {
            "task": task,
            "model": self.model,
            # Потолок обязателен: без него запрос не уходит.
            "maxCostUsd": cost,
        }
        browser_settings: dict[str, Any] = {}
        # Прокси указываем только вместе с browserSettings, иначе поле игнорируется.
        if proxy_country_code:
            browser_settings["proxyCountryCode"] = clamp_proxy_country(
                proxy_country_code
            )
        if record:
            browser_settings["record"] = True
        if browser_settings:
            body["browserSettings"] = browser_settings
        if session_id:
            body["sessionId"] = session_id
        return await self._request("POST", "/runs", json_body=body)

    async def get_status(self, run_id: str) -> str:
        """Дешёвый статус без чтения полного run'а."""
        payload = await self._request("GET", f"/runs/{run_id}/status")
        return str(payload.get("status") or "")

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/runs/{run_id}")

    async def cancel_run(self, run_id: str) -> bool:
        """Отменить брошенный run. Лучше довести до конца, чем оставить платным."""
        try:
            await self._request("POST", f"/runs/{run_id}/cancel")
            return True
        except BrowserUseError as exc:
            logger.warning("[browser_use] cancel {} не удался: {}", run_id, exc)
            return False

    async def stop_browser(self, session_id: str | None) -> bool:
        """Остановить облачный браузер.

        Завершившийся run сам по себе браузер не гасит, а биллинг за него
        продолжает идти. Остановка возвращает неиспользованное время.
        """
        if not session_id:
            return False
        try:
            await self._request(
                "PATCH", f"/browsers/{session_id}", json_body={"action": "stop"}
            )
            return True
        except BrowserUseError as exc:
            # 404 здесь безопасен: браузер уже мог быть остановлен или удалён.
            logger.info("[browser_use] stop browser {} не выполнен: {}", session_id, exc)
            return False

    # ── ожидание ──────────────────────────────────────────────────────
    async def wait_for_completion(
        self,
        run_id: str,
        *,
        timeout: float = 300.0,
        poll_interval: float = 3.0,
        on_timeout: str = "cancel",
    ) -> str:
        """Опрашивать статус до терминального.

        ``on_timeout='cancel'`` отменяет run, чтобы он не продолжал жечь
        деньги после нашего таймаута.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(1.0, timeout)
        delay = max(0.5, poll_interval)
        status = ""
        while True:
            status = await self.get_status(run_id)
            if status in TERMINAL_STATUSES:
                return status
            if loop.time() >= deadline:
                if on_timeout == "cancel":
                    await self.cancel_run(run_id)
                raise BrowserUseRunTimeout(
                    f"Run {run_id} не завершился за {int(timeout)}с "
                    f"(последний статус: {status or 'неизвестен'})"
                )
            await asyncio.sleep(delay)
            # Мягкий backoff, чтобы не упираться в rate limit на длинных run'ах.
            delay = min(delay * 1.3, 15.0)

    async def run_task(
        self,
        task: str,
        *,
        max_cost_usd: float | None = None,
        proxy_country_code: str | None = None,
        record: bool = False,
        timeout: float = 300.0,
        poll_interval: float = 3.0,
    ) -> RunResult:
        """Полный цикл: создать → дождаться → прочитать → гасить браузер.

        Браузер останавливается в ``finally`` при любом исходе, включая
        таймаут: незакрытый браузер продолжает тарифицироваться.
        """
        created = await self.create_run(
            task,
            max_cost_usd=max_cost_usd,
            proxy_country_code=proxy_country_code,
            record=record,
        )
        run_id = str(created.get("id") or "")
        session_id = created.get("sessionId")
        if not run_id:
            raise BrowserUseError("Browser Use не вернул id запуска")

        try:
            status = await self.wait_for_completion(
                run_id, timeout=timeout, poll_interval=poll_interval
            )
            payload = await self.get_run(run_id)
        except BrowserUseRunTimeout:
            await self.stop_browser(session_id)
            raise
        except BrowserUseError:
            await self.cancel_run(run_id)
            await self.stop_browser(session_id)
            raise
        else:
            # Успех и неуспех одинаково требуют остановки браузера.
            await self.stop_browser(session_id)
            return self._to_result(run_id, status, payload)

    def _to_result(self, run_id: str, status: str, payload: dict[str, Any]) -> RunResult:
        result = RunResult(
            run_id=run_id,
            status=status,
            result=str(payload.get("result") or ""),
            total_cost_usd=coerce_money(payload.get("totalCostUsd")),
            model=str(payload.get("model") or self.model),
            session_id=payload.get("sessionId"),
            title=str(payload.get("title") or ""),
            error=str(payload.get("error") or "")[:500],
            raw=payload,
        )
        if not result.ok:
            raise BrowserUseRunFailed(
                f"Run завершился со статусом {status or 'неизвестен'}",
                status=status,
                detail=result.error,
            )
        return result


def get_v4_client(**kwargs: Any) -> BrowserUseV4Client:
    """Фабрика клиента из настроек сервера."""
    settings = get_settings()
    return BrowserUseV4Client(
        model=getattr(settings, "browser_use_model", DEFAULT_MODEL),
        max_cost_usd=getattr(
            settings, "browser_use_max_cost_usd", DEFAULT_MAX_COST_USD
        ),
        **kwargs,
    )
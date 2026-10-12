"""Сбор и пересылка ошибок приложения.

Зачем
----
Пользователь раньше мог увидеть «что-то сломалось» только по логам на
сервере. Здесь ошибки с обоих концов — frontend и backend — попадают в
одно место и уходят владельцу в Telegram.

Без новых зависимостей: Sentry в проекте не установлен, а Telegram-бот
уже есть. Поэтому используем его.

Что НЕ уходит
-------------
Телефоны, email, токены, ключи, тексты тендеров и переписки. Из ошибки
вырезаются потенциально чувствительные поля, а текст ограничивается по
длине. Ошибка — это диагностика, а не дамп данных клиента.

Повторы ограничены: одинаковые ошибки не спамят (дедуп по хэшу за окно),
иначе одна петля в фронтенде завалила бы Telegram.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

#: Окно дедупликации: одна и та же ошибка уходит не чаще.
DEDUP_WINDOW_SEC = 900

#: Максимум уведомлений в час — страховка от шторма ошибок.
RATE_LIMIT_PER_HOUR = 20

MAX_MESSAGE_CHARS = 900
MAX_STACK_CHARS = 1200

#: Поля, которые нельзя пересылать ни в каком виде.
_SENSITIVE_KEYS = re.compile(
    r"(pass|secret|token|key|auth|cookie|session|email|phone|bin|card|cvv)", re.IGNORECASE
)

#: Явные секреты в тексте ошибки.
_SECRET_PATTERNS = (
    re.compile(r"bu_[A-Za-z0-9_\-]{16,}"),
    re.compile(r"tvly-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}"),  # JWT
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"\+7[\s\-()]*\d{3}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}"),
)


def scrub(text: str | None) -> str:
    """Убрать из текста секреты, контакты и длинные строки."""
    if not text:
        return ""
    cleaned = str(text)
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[скрыто]", cleaned)
    return cleaned[:MAX_STACK_CHARS]


def scrub_payload(value: Any, depth: int = 0) -> Any:
    """Рекурсивно вычистить структуру: убрать чувствительные ключи."""
    if depth > 4:
        return "[глубоко]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:40]:
            if _SENSITIVE_KEYS.search(str(key)):
                out[str(key)] = "[скрыто]"
            else:
                out[str(key)] = scrub_payload(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub_payload(v, depth + 1) for v in list(value)[:20]]
    if isinstance(value, str):
        return scrub(value)[:300]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return scrub(str(value))[:300]


def fingerprint(kind: str, message: str, where: str = "") -> str:
    """Стабильный хэш для дедупликации."""
    raw = f"{kind}|{where}|{message[:300]}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


@dataclass(slots=True)
class ErrorReporter:
    """Накопитель и отправитель ошибок.

    Держит состояние в памяти процесса: этого достаточно, чтобы не слать
    100 одинаковых сообщений, и не нужно поднимать инфраструктуру.
    """

    bot_token: str = ""
    admin_ids: list[int] = field(default_factory=list)
    app_env: str = "dev"
    enabled: bool = True
    _seen: dict[str, float] = field(default_factory=dict)
    _sent_times: list[float] = field(default_factory=list)
    _lock: Any = None

    def __post_init__(self) -> None:
        if not self._lock:
            import asyncio

            self._lock = asyncio.Lock()

    # ── дедупликация ──────────────────────────────────────────────
    def _should_send(self, key: str) -> bool:
        now = time.monotonic()
        self._seen = {k: v for k, v in self._seen.items() if now - v < DEDUP_WINDOW_SEC}
        self._sent_times = [t for t in self._sent_times if now - t < 3600]
        if len(self._sent_times) >= RATE_LIMIT_PER_HOUR:
            return False
        if key in self._seen:
            return False
        self._seen[key] = now
        self._sent_times.append(now)
        return True

    def format_message(self, report: dict[str, Any]) -> str:
        kind = report.get("source", "error")
        name = str(report.get("name") or "Error")[:80]
        message = scrub(str(report.get("message") or ""))[:MAX_MESSAGE_CHARS]
        where = str(report.get("where") or "")[:200]
        env = report.get("app_env", self.app_env)

        icon = "🖥" if kind == "backend" else "📱"
        lines = [
            f"{icon} *{kind}* ошибка · `{env}`",
            f"*{name}*: {message}",
        ]
        if where:
            lines.append(f"📍 `{where}`")
        user = report.get("user_hint")
        if user:
            lines.append(f"👤 {scrub(str(user))}")
        stack = scrub(str(report.get("stack") or ""))
        if stack:
            lines.append(f"\n<pre>{stack[:400]}</pre>")
        return "\n".join(lines)[:3900]  # лимит Telegram на сообщение

    async def _post(self, method: str, url: str, *, payload: Any = None) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if payload is None:
                    resp = await client.get(url)
                else:
                    resp = await client.post(url, json=payload)
                return resp.status_code < 400
        except httpx.HTTPError as exc:
            logger.warning("[errors] не удалось отправить в Telegram: {}", exc)
            return False

    async def report(self, report: dict[str, Any]) -> bool:
        """Отправить ошибку владельцу. Возвращает True, если ушло."""
        if not self.enabled or not self.bot_token or not self.admin_ids:
            logger.error("[errors] {}", scrub(str(report.get("message"))))
            return False

        key = fingerprint(
            str(report.get("name") or ""),
            str(report.get("message") or ""),
            str(report.get("where") or ""),
        )
        async with self._lock:
            if not self._should_send(key):
                logger.info("[errors] дубль подавлен: {}", key)
                return False

            text = self.format_message(report)
            ok = False
            for admin_id in self.admin_ids:
                sent = await self._post(
                    "post",
                    f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                    payload={"chat_id": admin_id, "text": text, "parse_mode": "HTML"},
                )
                ok = ok or sent
            logger.error("[errors] {} (уведомление {})", scrub(str(report.get("message"))), "отправлено" if ok else "не отправлено")
            return ok


_reporter: ErrorReporter | None = None


def get_reporter() -> ErrorReporter:
    """Создать репортер из настроек сервера (один раз на процесс)."""
    global _reporter
    if _reporter is not None:
        return _reporter
    from app.core.config import get_settings

    settings = get_settings()
    token = (getattr(settings, "bot_token", "") or "").strip()
    admin_ids = list(getattr(settings, "admin_ids_list", []) or [])
    _reporter = ErrorReporter(
        bot_token=token,
        admin_ids=admin_ids,
        app_env=getattr(settings, "app_env", "dev"),
        # В проде включаем всегда, в dev — тоже полезно для отладки.
        enabled=bool(token and admin_ids),
    )
    return _reporter

"""Черновики писем и планы звонка (F3–F5 ТЗ).

Модуль готовит МАТЕРИАЛЫ для одобрения и НИЧЕГО не отправляет сам.
Фактическая отправка живёт в services/outreach.py и доступна только из
одобренной записи approval_queue.

Режимы работы с поставщиком (F4):
  * ``manual`` — только черновик, отправка недоступна;
  * ``review`` — черновик показывается, отправляет пользователь после проверки;
  * ``trusted`` — автоотправка в пределах дневного лимита и без стоп-слов.

Режим хранится на карточке поставщика и понижается до ``review`` для
блок-листа и при превышении лимита: fail-safe по умолчанию.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.agents.base import Agent
from app.services.price_policy import (
    FORBIDDEN_AGENT_TOOLS,
    PriceAction,
    agent_toolset,
)

KZ_TZ = ZoneInfo("Asia/Almaty")

#: Режимы отправки (F4).
MODE_MANUAL = "manual"
MODE_REVIEW = "review"
MODE_TRUSTED = "trusted"
VALID_MODES = frozenset({MODE_MANUAL, MODE_REVIEW, MODE_TRUSTED})

#: Стоп-слова, при которых trusted-автоотправка запрещена (F4).
STOP_WORDS: tuple[str, ...] = (
    "договор",
    "контракт",
    "подписать",
    "оплатить",
    "предоплата",
    "гарантийный депозит",
    "подписка на договор",
    "accept price",
)

#: Фразы, которые агент не имеет права произносить (F6 — обязательства).
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "мы принимаем ваши условия",
    "согласны на вашу цену",
    "подписываем договор",
    "оплачиваем",
    "гарантируем оплату",
)

MAX_DRAFT_CHARS = 4000
MAX_PLAN_ITEMS = 8


def normalize_mode(mode: str | None) -> str:
    value = str(mode or "").strip().lower()
    return value if value in VALID_MODES else MODE_REVIEW


def effective_mode(requested: str | None, *, blocked: bool = False, daily_sent: int = 0, daily_limit: int = 0) -> str:
    """Фактический режим с учётом ограничений.

    ``manual`` не повышается никогда. ``trusted`` понижается до ``review``,
    если поставщик в стоп-листе или исчерпан дневной лимит.
    """
    mode = normalize_mode(requested)
    if mode == MODE_MANUAL:
        return MODE_MANUAL
    if mode == MODE_TRUSTED and (blocked or daily_sent >= daily_limit > 0):
        return MODE_REVIEW
    return mode


def has_stop_word(text: str) -> str | None:
    """Первое стоп-слово в тексте, если есть."""
    lowered = (text or "").lower()
    for word in STOP_WORDS:
        if word in lowered:
            return word
    return None


def find_forbidden_phrase(text: str) -> str | None:
    lowered = (text or "").lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def sanitize_draft(text: str) -> str:
    """Убрать обещания обязательств и лишние пробелы.

    Финальный страх: даже если LLM «забыл» правило, формулировки с
    обязательствами вырезаются перед показом пользователю.
    """
    cleaned = (text or "").strip()
    for phrase in FORBIDDEN_PHRASES:
        cleaned = re.sub(re.escape(phrase), "[фраза удалена]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned[:MAX_DRAFT_CHARS]


@dataclass(slots=True)
class CompanyContacts:
    """Рабочие контакты пользователя — подставляются в исходящие материалы.

    Хранятся в company_profiles и НЕ передаются в сторонние сервисы:
    в письме они идут в подписи, в сценарии звонка — в блоке представления.
    """

    contact_name: str = ""
    company_name: str = ""
    work_email: str = ""
    work_phone: str = ""

    def signature_lines(self) -> list[str]:
        lines = []
        if self.contact_name:
            lines.append(self.contact_name)
        if self.company_name:
            lines.append(self.company_name)
        if self.work_phone:
            lines.append(f"Тел.: {self.work_phone}")
        if self.work_email:
            lines.append(f"E-mail: {self.work_email}")
        return lines


@dataclass(slots=True)
class CallPlan:
    """План звонка, который пользователь одобряет до вызова агента (F5)."""

    goal: str = ""
    questions: list[str] = field(default_factory=list)
    red_lines: list[str] = field(default_factory=list)
    exit_script: str = ""
    introduction: str = ""
    price_outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "questions": self.questions,
            "red_lines": self.red_lines,
            "exit_script": self.exit_script,
            "introduction": self.introduction,
            "price_outcome": self.price_outcome,
        }


def is_working_hours_kz(now: datetime | None = None) -> bool:
    """Проверка «рабочее время Казахстана» (НФТ, F5).

    Пн–Пт 09:00–18:00, Алматы. За пределами окна звонок не запускается.
    """
    moment = now or datetime.now(KZ_TZ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KZ_TZ)
    moment = moment.astimezone(KZ_TZ)
    if moment.weekday() >= 5:
        return False
    return time(9, 0) <= moment.time() < time(18, 0)


def kz_day_start(now: datetime | None = None) -> datetime:
    """Начало «календарного дня» по Алматы (naive UTC для сравнения в БД)."""
    moment = now or datetime.now(KZ_TZ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KZ_TZ)
    moment = moment.astimezone(KZ_TZ)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC).replace(tzinfo=None)


def kz_day_end(now: datetime | None = None) -> datetime:
    return kz_day_start(now) + timedelta(days=1)


class OutreachAgent(Agent):
    """Готовит черновики писем и планы звонка. Отправляет — только backend."""

    name = "outreach_agent"

    system_prompt = """Ты готовишь ДЕЛОВЫЕ СООБЩЕНИЯ поставщикам по тендеру в Казахстане.

ЖЁСТКИЕ ПРАВИЛА:
1. Ты НЕ соглашаешься на цену, НЕ подписываешь договор, НЕ берёшь
   обязательств. Ты только задаёшь вопросы и собираешь информацию.
2. Если цена не устраивает — скажи об этом и спроси о возможной корректировке.
   Никогда не пиши, что принимаешь их условия.
3. Письмо — до 200 слов, по-русски, деловой тон. Без спама и обещаний.
4. Задай конкретные вопросы: цена за единицу, наличие, сроки поставки,
   сертификаты, гарантия, условия для Казахстана.
5. Пиши от лица компании пользователя, используй ТОЛЬКО контакты,
   которые тебе даны в подписи.

Верни валидный JSON с одним из двух объектов:
{"email": {"subject": "...", "body": "..."}}  — когда готовим письмо
{"call_plan": {"goal": "...", "questions": ["..."], "red_lines": ["..."],
  "exit_script": "...", "introduction": "..."}} — когда готовим план звонка"""

    def __init__(self) -> None:
        # Набор инструментов фиксирован и не содержит операций сделки (F6).
        self.tools = agent_toolset()
        self.forbidden_tools = FORBIDDEN_AGENT_TOOLS

    async def run(self, kind: str = "email", **kwargs) -> dict[str, Any]:
        """Точка входа агента (контракт Agent.run).

        kind: ``email`` — черновик письма, ``call`` — план звонка.
        Остальные аргументы передаются в соответствующий метод без изменений.
        """
        if kind == "call":
            plan = await self.draft_call_plan(**kwargs)
            return {"call_plan": plan}
        draft = await self.draft_email(**kwargs)
        return {"email": draft}

    async def draft_email(
        self,
        *,
        supplier_name: str,
        lot_title: str,
        requirements: list[str],
        contacts: CompanyContacts,
        known_price_kzt: float | None = None,
        price_action: PriceAction | None = None,
        counter_script: str | None = None,
    ) -> dict[str, Any]:
        """Черновик письма поставщику."""
        req_block = "\n".join(f"- {r}" for r in requirements[:12])
        price_hint = f"Ориентировочный бюджет: {known_price_kzt} тг." if known_price_kzt else ""
        prompt = (
            f"Поставщик: {supplier_name}\n"
            f"Закупка: {lot_title}\n"
            f"Требования ТЗ:\n{req_block}\n{price_hint}\n"
            f"Подпись отправителя:\n" + "\n".join(contacts.signature_lines()) + "\n\n"
        )
        if price_action is PriceAction.COUNTER_ONCE:
            prompt += (
                "Цена поставщика выше нашего бюджета. Сформулируй вежливую просьбу "
                "о корректировке цены в меньшую сторону, без обещаний и обязательств.\n"
            )
        elif price_action is PriceAction.DECLINE:
            prompt += (
                "Цена неприемлема. Не предлагай сделку — поблагодари и оставь "
                "возможность вернуться к вопросу позже.\n"
            )
        prompt += 'Верни JSON {"email": {"subject": "...", "body": "..."}}.'

        data = await self._chat_json(prompt, max_tokens=1200)
        email = data.get("email") if isinstance(data.get("email"), dict) else {}
        subject = str(email.get("subject") or f"Запрос по закупке: {lot_title[:120]}")[:200]
        body = sanitize_draft(str(email.get("body") or ""))
        if not body:
            # Честный пустой результат вместо выдуманного письма.
            return {
                "subject": subject,
                "body": "",
                "blocked_phrase": None,
                "has_stop_word": has_stop_word(subject),
                "ok": False,
            }
        return {
            "subject": subject,
            "body": body,
            "blocked_phrase": find_forbidden_phrase(body),
            "has_stop_word": has_stop_word(f"{subject} {body}"),
            "ok": True,
        }

    async def draft_call_plan(
        self,
        *,
        supplier_name: str,
        lot_title: str,
        requirements: list[str],
        contacts: CompanyContacts,
        price_action: PriceAction | None = None,
        counter_script: str | None = None,
    ) -> dict[str, Any]:
        """План телефонного разговора для одобрения пользователем."""
        req_block = "\n".join(f"- {r}" for r in requirements[:12])
        prompt = (
            f"Поставщик: {supplier_name}\n"
            f"Закупка: {lot_title}\n"
            f"Пункты ТЗ:\n{req_block}\n"
            f"Кто звонит: " + ", ".join(filter(None, [contacts.contact_name, contacts.company_name])) + "\n\n"
            "Составь план звонка: цель, 3–5 вопросов, красные линии (чего не говорим), "
            "фраза выхода. В представлении обязательно назвать компанию и цель звонка.\n"
        )
        if price_action is PriceAction.COUNTER_ONCE:
            prompt += "Цена выше бюджета — предусмотри один вежливый вопрос о корректировке.\n"
        elif price_action is PriceAction.DECLINE:
            prompt += "Цена неприемлема — сценарий должен завершиться без обязательств.\n"
        prompt += (
            'Верни JSON {"call_plan": {"goal": "...", "questions": ["..."], '
            '"red_lines": ["..."], "exit_script": "...", "introduction": "..."}}.'
        )

        data = await self._chat_json(prompt, max_tokens=1500)
        raw = data.get("call_plan") if isinstance(data.get("call_plan"), dict) else {}
        introduction = str(raw.get("introduction") or "")[:400]
        if not introduction:
            who = contacts.company_name or contacts.contact_name or "компания"
            introduction = (
                f"Здравствуйте! Меня зовут {contacts.contact_name or 'представитель'}, "
                f"компания {who}. Звоню по вопросу участия в закупке: {lot_title[:120]}. "
                "Удобно сейчас говорить?"
            )
        plan = CallPlan(
            goal=str(raw.get("goal") or "")[:500],
            questions=[str(q)[:300] for q in (raw.get("questions") or [])][:MAX_PLAN_ITEMS],
            red_lines=[str(r)[:300] for r in (raw.get("red_lines") or [])][:MAX_PLAN_ITEMS],
            exit_script=str(raw.get("exit_script") or "")[:500],
            introduction=introduction,
            price_outcome=price_action.value if price_action else None,
        )
        # Красные линии дополняем техническими запретами F6.
        for phrase in ("Не соглашаться на цену без одобрения пользователя", "Не обещать сроки и условия"):
            if phrase not in plan.red_lines:
                plan.red_lines.append(phrase)
        text_dump = f"{plan.goal} {' '.join(plan.questions)} {plan.exit_script}"
        return {
            **plan.to_dict(),
            "has_stop_word": has_stop_word(text_dump),
            "ok": bool(plan.goal or plan.questions),
        }


def validate_draft_for_send(draft: dict[str, Any]) -> tuple[bool, str | None]:
    """Финальный гейт перед отправкой: что можно отправить, а что нет.

    Возвращает ``(ok, reason)``. ``reason`` — машинный код для фронтенда.
    """
    if not draft.get("ok"):
        return False, "DRAFT_EMPTY"
    if draft.get("blocked_phrase"):
        return False, "DRAFT_HAS_OBLIGATION"
    if draft.get("has_stop_word"):
        return False, "DRAFT_HAS_STOP_WORD"
    body = str(draft.get("body") or draft.get("introduction") or "")
    if not body.strip():
        return False, "DRAFT_EMPTY"
    return True, None


__all__ = [
    "FORBIDDEN_PHRASES",
    "MODE_MANUAL",
    "MODE_REVIEW",
    "MODE_TRUSTED",
    "STOP_WORDS",
    "CallPlan",
    "CompanyContacts",
    "OutreachAgent",
    "effective_mode",
    "has_stop_word",
    "is_working_hours_kz",
    "kz_day_end",
    "kz_day_start",
    "normalize_mode",
    "sanitize_draft",
    "validate_draft_for_send",
]
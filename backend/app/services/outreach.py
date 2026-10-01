"""Исходящие действия: письма (F4) и звонки (F5).

Ключевое правило всего модуля: исходящее действие возможно ТОЛЬКО из
одобренной записи approval_queue. Здесь нет «отправить напрямую» — функция
принимает approval_id и сама проверяет статус. Это архитектурный запрет (F6),
а не проверка на стороне вызывающего кода.

Дополнительные гейты:
* режим ``manual`` — отправка невозможна в принципе;
* ``trusted`` — уважает дневной лимит и стоп-слова;
* стоп-лист поставщика — блокирует любое действие;
* звонки — только в рабочее время Казахстана;
* email/call провайдеры вынесены в адаптеры и отключены по умолчанию,
  пока юрист не подтвердит обработку ПДн (ТЗ §4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from loguru import logger

from app.agents.outreach_agent import (
    MODE_MANUAL,
    CompanyContacts,
    effective_mode,
    is_working_hours_kz,
    kz_day_start,
    validate_draft_for_send,
)
from app.db import supplier_repo as repo
from app.services.price_policy import PriceAction, decline_text


class OutreachNotAllowed(RuntimeError):
    """Исходящее действие запрещено политикой или не одобрено."""


class EmailProvider(Protocol):
    """Абстракция отправки письма (SMTP/OAuth-адаптер подставляется позже)."""

    async def send(
        self, *, to_email: str, subject: str, body: str, reply_to: str | None
    ) -> dict[str, Any]: ...


class CallProvider(Protocol):
    """Абстракция телефонного звонка (Leximo MCP-адаптер подставляется позже)."""

    async def place_call(
        self, *, to_phone: str, scenario: dict[str, Any], metadata: dict[str, str]
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class DisabledEmailProvider:
    """Заглушка: реальная отправка выключена до заключения юриста (ПДн)."""

    reason: str = "EMAIL_DISABLED_PENDING_LEGAL"

    async def send(
        self, *, to_email: str, subject: str, body: str, reply_to: str | None
    ) -> dict[str, Any]:
        raise OutreachNotAllowed(self.reason)


@dataclass(slots=True)
class DisabledCallProvider:
    """Заглушка звонков: Leximo не подключён и ПДн не согласованы."""

    reason: str = "CALL_DISABLED_PENDING_LEGAL"

    async def place_call(
        self, *, to_phone: str, scenario: dict[str, Any], metadata: dict[str, str]
    ) -> dict[str, Any]:
        raise OutreachNotAllowed(self.reason)


@dataclass(slots=True)
class SendResult:
    job_id: int
    status: str
    mode: str
    external_id: str | None = None
    cost_usd: float = 0.0


class OutreachService:
    """Оркестратор исходящих действий с проверкой всех ограничений."""

    def __init__(
        self,
        *,
        email_provider: EmailProvider | None = None,
        call_provider: CallProvider | None = None,
        daily_email_limit: int = 20,
        daily_call_limit: int = 5,
        daily_call_budget_usd: float = 5.0,
    ) -> None:
        self._email = email_provider or DisabledEmailProvider()
        self._call = call_provider or DisabledCallProvider()
        self.daily_email_limit = daily_email_limit
        self.daily_call_limit = daily_call_limit
        self.daily_call_budget_usd = daily_call_budget_usd

    # ── Проверки (единая точка для обоих каналов) ──────────────────────
    async def _assert_outreach_allowed(
        self, session, *, user_id: int, approval_id: int, recipient_supplier: str
    ):
        approval = await repo.get_approval(session, user_id, approval_id)
        if approval is None:
            raise OutreachNotAllowed("APPROVAL_NOT_FOUND")
        if approval.status != "approved":
            # Главный гейт: без явного одобрения пользователя — никаких действий.
            raise OutreachNotAllowed("APPROVAL_REQUIRED")

        candidate = None
        if approval.candidate_id is not None:
            candidate = await repo.get_candidate(session, user_id, approval.candidate_id)
        if candidate is not None and await repo.is_blocked(session, user_id, candidate.supplier):
            raise OutreachNotAllowed("SUPPLIER_BLOCKED")
        return approval, candidate

    def _check_draft(self, approval) -> None:
        draft_payload = {"ok": bool(approval.draft_text), "body": approval.draft_text}
        plan_payload = {"ok": bool(approval.plan_json), "introduction": approval.plan_json}
        payload = draft_payload if approval.kind == "email" else plan_payload
        ok, reason = validate_draft_for_send(payload)
        if not ok:
            raise OutreachNotAllowed(reason or "DRAFT_INVALID")

    def _resolve_mode(self, requested: str | None, *, blocked: bool, sent: int, limit: int) -> str:
        return effective_mode(
            requested, blocked=blocked, daily_sent=sent, daily_limit=limit
        )

    # ── Письма (F4) ────────────────────────────────────────────────────
    async def send_approved_email(
        self,
        session,
        *,
        user_id: int,
        approval_id: int,
        subject: str,
        contacts: CompanyContacts,
        daily_limit: int | None = None,
    ) -> SendResult:
        """Отправить письмо по одобренному черновику."""
        approval, candidate = await self._assert_outreach_allowed(
            session, user_id=user_id, approval_id=approval_id, recipient_supplier=""
        )
        if approval.kind != "email":
            raise OutreachNotAllowed("APPROVAL_KIND_MISMATCH")
        self._check_draft(approval)

        profile = await repo.get_or_create_company_profile(session, user_id)
        blocked = False
        if candidate is not None and await repo.is_blocked(session, user_id, candidate.supplier):
            blocked = True

        limit = daily_limit or self.daily_email_limit
        sent_today = await repo.count_jobs_today(
            session, user_id, "email", since=kz_day_start()
        )
        mode = self._resolve_mode(getattr(profile, "outreach_mode", None), blocked=blocked, sent=sent_today, limit=limit)

        if mode == MODE_MANUAL:
            raise OutreachNotAllowed("MANUAL_MODE_BLOCKS_SENDING")
        if sent_today >= limit:
            raise OutreachNotAllowed("DAILY_EMAIL_LIMIT_REACHED")

        recipient = ""
        if candidate is not None:
            recipient = str((candidate.card_json or {}).get("email") or "")[:255]
        if not recipient:
            # Без явного адресата письмо уходить не может — риск «письма в никуда».
            raise OutreachNotAllowed("RECIPIENT_EMAIL_MISSING")

        job = await repo.create_outreach_job(
            session,
            user_id=user_id,
            approval_id=approval_id,
            kind="email",
            recipient=recipient,
            status="queued",
        )
        try:
            result = await self._email.send(
                to_email=recipient,
                subject=subject[:200],
                body=approval.draft_text,
                reply_to=contacts.work_email or None,
            )
        except OutreachNotAllowed:
            await repo.log_action(
                session,
                user_id=user_id,
                action="email",
                target=recipient,
                detail_json={"outcome": "blocked", "mode": mode},
            )
            raise
        except Exception as exc:
            logger.warning("[outreach] email failed: {}", exc)
            job.status = "failed"
            await session.flush()
            await repo.log_action(
                session,
                user_id=user_id,
                action="email",
                target=recipient,
                detail_json={"outcome": "failed", "mode": mode},
            )
            raise OutreachNotAllowed("EMAIL_SEND_FAILED") from exc

        job.status = str(result.get("status") or "sent")
        job.external_id = (result.get("id") or None)
        job.cost_usd = float(result.get("cost_usd") or 0.0)
        await session.flush()
        await repo.log_action(
            session,
            user_id=user_id,
            action="email",
            target=recipient,
            detail_json={"outcome": job.status, "mode": mode},
        )
        return SendResult(
            job_id=job.id,
            status=job.status,
            mode=mode,
            external_id=job.external_id,
            cost_usd=job.cost_usd,
        )

    # ── Звонки (F5) ────────────────────────────────────────────────────
    async def place_approved_call(
        self,
        session,
        *,
        user_id: int,
        approval_id: int,
        now: datetime | None = None,
        daily_limit: int | None = None,
    ) -> SendResult:
        """Инициировать звонок по одобренному плану."""
        approval, candidate = await self._assert_outreach_allowed(
            session, user_id=user_id, approval_id=approval_id, recipient_supplier=""
        )
        if approval.kind != "call":
            raise OutreachNotAllowed("APPROVAL_KIND_MISMATCH")
        self._check_draft(approval)

        if not is_working_hours_kz(now):
            # Жёсткое ограничение НФТ: только рабочее время КЗ.
            raise OutreachNotAllowed("OUTSIDE_WORKING_HOURS_KZ")

        profile = await repo.get_or_create_company_profile(session, user_id)
        blocked = False
        if candidate is not None and await repo.is_blocked(session, user_id, candidate.supplier):
            blocked = True

        limit = daily_limit or self.daily_call_limit
        calls_today = await repo.count_jobs_today(session, user_id, "call", since=kz_day_start())
        spend_today = await repo.sum_call_cost_since(session, user_id, since=kz_day_start())
        if spend_today >= self.daily_call_budget_usd:
            raise OutreachNotAllowed("DAILY_CALL_BUDGET_REACHED")

        mode = self._resolve_mode(getattr(profile, "outreach_mode", None), blocked=blocked, sent=calls_today, limit=limit)
        if mode == MODE_MANUAL:
            raise OutreachNotAllowed("MANUAL_MODE_BLOCKS_CALLING")
        if calls_today >= limit:
            raise OutreachNotAllowed("DAILY_CALL_LIMIT_REACHED")

        phone = ""
        if candidate is not None:
            phone = str((candidate.card_json or {}).get("phone") or "")[:32]
        if not phone:
            raise OutreachNotAllowed("RECIPIENT_PHONE_MISSING")

        job = await repo.create_outreach_job(
            session,
            user_id=user_id,
            approval_id=approval_id,
            kind="call",
            recipient=phone,
            status="queued",
        )
        try:
            result = await self._call.place_call(
                to_phone=phone,
                scenario=approval.plan_json or {},
                metadata={"user_id": str(user_id), "approval_id": str(approval_id)},
            )
        except OutreachNotAllowed:
            await repo.log_action(
                session,
                user_id=user_id,
                action="call",
                target=phone,
                detail_json={"outcome": "blocked", "mode": mode},
            )
            raise
        except Exception as exc:
            logger.warning("[outreach] call failed: {}", exc)
            job.status = "failed"
            await session.flush()
            await repo.log_action(
                session,
                user_id=user_id,
                action="call",
                target=phone,
                detail_json={"outcome": "failed", "mode": mode},
            )
            raise OutreachNotAllowed("CALL_FAILED") from exc

        job.status = str(result.get("status") or "queued")
        job.external_id = (result.get("id") or None)
        job.cost_usd = float(result.get("cost_usd") or 0.0)
        job.price_outcome = result.get("price_outcome")
        job.transcription = result.get("transcription")
        await session.flush()
        await repo.log_action(
            session,
            user_id=user_id,
            action="call",
            target=phone,
            detail_json={"outcome": job.status, "mode": mode, "price_outcome": job.price_outcome},
            call_cost_usd=job.cost_usd,
        )
        return SendResult(
            job_id=job.id,
            status=job.status,
            mode=mode,
            external_id=job.external_id,
            cost_usd=job.cost_usd,
        )

    # ── Политика цены в исходящем контексте (F6) ───────────────────────
    def price_message(
        self, action: PriceAction, *, counter_script: str | None = None
    ) -> str:
        """Текст, который агент произносит по цене. Без обязательств."""
        if action is PriceAction.DECLINE:
            return decline_text("over_limit", counter_script=counter_script)
        if action is PriceAction.COUNTER_ONCE:
            return counter_script or "Возможна ли корректировка цены в меньшую сторону?"
        return ""


__all__ = [
    "DisabledCallProvider",
    "DisabledEmailProvider",
    "OutreachNotAllowed",
    "OutreachService",
    "SendResult",
]
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
* email/call провайдеры вынесены в адаптеры и включаются только явной
  серверной конфигурацией; без неё UI предлагает ручной безопасный режим.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, Protocol

import httpx
from loguru import logger

from app.agents.outreach_agent import (
    MODE_MANUAL,
    KZ_TZ,
    CompanyContacts,
    effective_mode,
    is_working_hours_kz,
    kz_day_start,
    validate_draft_for_send,
)
from app.db import supplier_repo as repo
from app.core.config import get_settings
from app.services.price_policy import PriceAction, decline_text


class OutreachNotAllowed(RuntimeError):
    """Исходящее действие запрещено политикой или не одобрено."""


class EmailProvider(Protocol):
    """Абстракция отправки письма через настроенный серверный адаптер."""

    async def send(
        self, *, to_email: str, subject: str, body: str, reply_to: str | None
    ) -> dict[str, Any]: ...


class CallProvider(Protocol):
    """Абстракция телефонного звонка через настроенный серверный адаптер."""

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
class SmtpEmailProvider:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    starttls: bool = True
    use_ssl: bool = False

    async def send(
        self, *, to_email: str, subject: str, body: str, reply_to: str | None
    ) -> dict[str, Any]:
        message = EmailMessage()
        message["From"] = self.from_email
        message["To"] = to_email
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=self.from_email.partition("@")[2] or None)
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(body)

        def _send() -> None:
            context = ssl.create_default_context()
            connection = (
                smtplib.SMTP_SSL(self.host, self.port, timeout=20, context=context)
                if self.use_ssl
                else smtplib.SMTP(self.host, self.port, timeout=20)
            )
            with connection as smtp:
                if self.starttls and not self.use_ssl:
                    smtp.starttls(context=context)
                if self.username:
                    smtp.login(self.username, self.password)
                smtp.send_message(message)

        await asyncio.to_thread(_send)
        return {"status": "sent", "id": str(message["Message-ID"]), "cost_usd": 0.0}


@dataclass(slots=True)
class LeximoCallProvider:
    """Leximo Calls REST adapter based on their official open-source MCP client."""

    api_token: str
    agent_id: str
    base_url: str = "https://concierge.leximo.ai"

    async def place_call(
        self, *, to_phone: str, scenario: dict[str, Any], metadata: dict[str, str]
    ) -> dict[str, Any]:
        questions = scenario.get("questions") or []
        red_lines = scenario.get("red_lines") or []
        task_parts = [str(scenario.get("goal") or scenario.get("introduction") or "Уточнить условия поставки")]
        if questions:
            task_parts.append("Вопросы: " + "; ".join(map(str, questions)))
        if red_lines:
            task_parts.append("Ограничения: " + "; ".join(map(str, red_lines)))
        task_parts.append("Не соглашаться на цену и не принимать юридических обязательств.")
        scheduled = datetime.now(KZ_TZ) + timedelta(minutes=2)
        payload = {
            "agentId": self.agent_id,
            "name": metadata.get("supplier") or "Поставщик по тендеру",
            "datetime": scheduled.isoformat(),
            "timezone": "Asia/Almaty",
            "phoneNumber": to_phone,
            "languageCode": "ru",
            "task": "\n".join(task_parts)[:4000],
            "notifications": True,
            "emailUpdates": True,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.base_url}/api/assignment",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                    "X-Source": "tendr",
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Leximo API returned HTTP {response.status_code}")
        data = response.json()
        assignment = data.get("data") if isinstance(data.get("data"), dict) else data
        assignment_id = str(assignment.get("id") or assignment.get("_id") or "")
        if not assignment_id:
            raise RuntimeError("Leximo API response has no assignment id")
        return {"status": "queued", "id": assignment_id, "cost_usd": 0.0}


def outreach_capabilities() -> dict[str, Any]:
    settings = get_settings()
    email_ready = bool(settings.smtp_host and settings.smtp_from_email)
    call_ready = bool(settings.leximo_api_token and settings.leximo_agent_id)
    return {
        "email": {"available": email_ready, "provider": "smtp" if email_ready else None},
        "call": {"available": call_ready, "provider": "leximo" if call_ready else None},
        "requires_approval": True,
        "manual_fallback": True,
    }


def configured_email_provider() -> EmailProvider:
    settings = get_settings()
    if not outreach_capabilities()["email"]["available"]:
        return DisabledEmailProvider("EMAIL_PROVIDER_NOT_CONFIGURED")
    return SmtpEmailProvider(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_email=settings.smtp_from_email,
        starttls=settings.smtp_starttls,
        use_ssl=settings.smtp_use_ssl,
    )


def configured_call_provider() -> CallProvider:
    settings = get_settings()
    if not outreach_capabilities()["call"]["available"]:
        return DisabledCallProvider("CALL_PROVIDER_NOT_CONFIGURED")
    return LeximoCallProvider(
        api_token=settings.leximo_api_token,
        agent_id=settings.leximo_agent_id,
    )


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
        self._email = email_provider or configured_email_provider()
        self._call = call_provider or configured_call_provider()
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
                metadata={
                    "user_id": str(user_id),
                    "approval_id": str(approval_id),
                    "supplier": candidate.supplier if candidate is not None else "",
                },
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
    "LeximoCallProvider",
    "OutreachNotAllowed",
    "OutreachService",
    "SmtpEmailProvider",
    "SendResult",
    "outreach_capabilities",
]

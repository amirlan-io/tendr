"""ORM-модели для persistence.

Схема:
- users: пользователи (Telegram ID или web client_id)
- analyses: история анализов лотов
- subscriptions: freemium/paid подписки
- payments: история платежей (для Kaspi Pay)
- discovery_subscriptions: подписки на уведомления о новых лотах по ключевым словам
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
# Портативный JSON-тип: на PostgreSQL используется JSONB (быстрее, индексируется),
# на других БД (например SQLite для тестов) — обычный JSON.
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Универсальный тип: JSONB на PostgreSQL, JSON на остальных БД (SQLite для тестов).
JSONType = JSON().with_variant(JSONB(), "postgresql")

# BigInteger на PostgreSQL, Integer на SQLite — иначе autoincrement не работает
# на SQLite (там autoincrement работает только для INTEGER PRIMARY KEY, а не BIGINT).
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class User(Base):
    """Пользователь системы: Telegram-бот или web-клиент."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # Telegram ID (0 = web-пользователь)
    telegram_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, index=True, nullable=True
    )
    # Web client_id (UUID из cookie/localStorage)
    web_client_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    # Контактные данные
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # Язык интерфейса: ru/kk
    language: Mapped[str] = mapped_column(String(2), default="ru")
    # Пилотный пользователь (безлимит)
    is_pilot: Mapped[bool] = mapped_column(Boolean, default=False)
    # Активная подписка
    is_subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Время создания и обновления
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    quota_reservations: Mapped[list["QuotaReservation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    discovery_subs: Mapped[list["DiscoverySubscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class WorkspaceState(Base):
    """Small user-owned UI state synchronized across browsers."""

    __tablename__ = "workspace_states"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    namespace: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict | list] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "namespace", name="uq_workspace_states_user_namespace"),
        Index("ix_workspace_states_user_namespace", "user_id", "namespace"),
    )


class QuotaReservation(Base):
    """БД-резервирование квоты на текущий месяц."""

    __tablename__ = "quota_reservations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reservation_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    operation_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, default=1)
    month_key: Mapped[str] = mapped_column(String(7), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="reserved", index=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="quota_reservations")

    __table_args__ = (
        Index("ix_quota_reservations_user_month_status", "user_id", "month_key", "status"),
    )


class Analysis(Base):
    """Результат анализа лота."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Идентификация лота
    lot_id: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Данные лота (денормализованные для быстрого отображения в истории)
    title: Mapped[str] = mapped_column(String(512), default="")
    customer: Mapped[str] = mapped_column(String(512), default="")
    method: Mapped[str] = mapped_column(String(64), default="other")
    budget_kzt: Mapped[float | None] = mapped_column(Float, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Полный результат анализа (JSON от LLM-агентов)
    result_json: Mapped[dict] = mapped_column(JSONType)
    # Метрики для быстрой фильтрации
    n_requirements: Mapped[int] = mapped_column(Integer, default=0)
    n_red_flags: Mapped[int] = mapped_column(Integer, default=0)
    overall_risk: Mapped[str] = mapped_column(String(32), default="needs_review")
    incomplete: Mapped[bool] = mapped_column(Boolean, default=False)
    # Время
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    # Срок жизни (для in-memory эквивалента TTL=24ч — но тут храним дольше для истории)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="analyses")

    __table_args__ = (
        Index("ix_analyses_user_created", "user_id", "created_at"),
        Index("ix_analyses_lot", "lot_id"),
    )


class AnalysisJob(Base):
    """Долгий анализ, который можно восстановить после перезагрузки страницы."""

    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # url / upload
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(160), default="Задание создано")
    input_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    result_json: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reservation_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_analysis_jobs_user_created", "user_id", "created_at"),
        Index("ix_analysis_jobs_user_status", "user_id", "status"),
    )


class Subscription(Base):
    """Подписка пользователя."""

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Тариф: "free" / "monthly" / "quarterly" / "yearly" / "pilot"
    plan: Mapped[str] = mapped_column(String(32))
    # Сколько анализов в месяц разрешено (999 = безлимит для пилота)
    monthly_limit: Mapped[int] = mapped_column(Integer, default=3)
    # Статус
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Внешний ID подписки (Kaspi Pay / Stripe)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship()


class Payment(Base):
    """История платежей."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Сумма в тенге
    amount_kzt: Mapped[float] = mapped_column(Float)
    # Метод: kaspi / stripe / manual
    method: Mapped[str] = mapped_column(String(32))
    # Статус: pending / succeeded / failed / refunded
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # Внешний ID (Kaspi Pay / Stripe)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Описание
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Время
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Сырой ответ от платёжки
    raw_response: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    user: Mapped[User] = relationship(back_populates="payments")


class DiscoverySubscription(Base):
    """Подписка на уведомления о новых лотах по ключевым словам."""

    __tablename__ = "discovery_subscriptions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Ключевые слова для поиска
    keywords: Mapped[str] = mapped_column(String(512))
    # Категория (опционально)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Регион (опционально)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Минимальная сумма
    min_budget_kzt: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Максимальная сумма
    max_budget_kzt: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Канал доставки: telegram / email
    channel: Mapped[str] = mapped_column(String(32), default="telegram")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="discovery_subs")

    __table_args__ = (
        UniqueConstraint("user_id", "keywords", "channel", name="uq_discovery_user_kw"),
    )


# ───── Каталог лотов (P0: конкуренция с ets-tender.kz) ─────


class Lot(Base):
    """Каталожная запись о лоте (тендере) с zakup.gov.kz и других площадок РК.

    Источники: zakup.gov.kz, goszakup.gov.kz, ets-tender.kz, samruk-astana.kz,
    tizilim.kz, erg.kz и 40+ других площадок агрегированных через TenderPlus.
    """

    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # Уникальный ID с источника (например "goszakup:1234567")
    source: Mapped[str] = mapped_column(
        String(64), index=True
    )  # zakup_gov, ets_tender, samruk, ...
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    # URL на оригинальный лот
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Основные данные
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Категория: товар / работа / услуга
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Способ закупки (тендер, аукцион, запрос цен и т.д.)
    procurement_method: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Площадка (Госзакупки, Самрук-Казына, ERG, Tizilim и т.д.)
    platform: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # Финансы
    amount_kzt: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    price_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)

    # География
    region: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Даты
    publish_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    deadline_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Заказчик
    organizer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    organizer_bin: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Статусы
    status: Mapped[str] = mapped_column(String(64), default="published", index=True)
    # Опубликован / Обсуждение / Приём заявок / Ожидание итогов / Завершён / Отменён

    # AI-метаданные (наши доработки)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_red_flags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    ai_match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    ai_processed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Служебное
    raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON от источника
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    partnerships: Mapped[list["LotPartnership"]] = relationship(
        back_populates="lot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_lot_source_id"),
        Index("ix_lots_status_deadline", "status", "deadline_date"),
        Index("ix_lots_platform_region", "platform", "region"),
    )


class LotPartnership(Base):
    """Заявка на партнёрство по лоту (B2B matchmaking — наш USP).

    4 типа ролей (как у TenderPlus):
    - supplier: "Могу поставить товар/услугу"
    - investor: "Могу профинансировать"
    - applicant: "Хочу подать заявку от своего имени"
    - partner: "Готов к любой форме сотрудничества"
    """

    __tablename__ = "lot_partnerships"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Роль: supplier / investor / applicant / partner
    role: Mapped[str] = mapped_column(String(32))
    # Сообщение (что предлагает)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Контакт (email, телефон)
    contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Статус: active / matched / closed
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    lot: Mapped[Lot] = relationship(back_populates="partnerships")
    user: Mapped[User] = relationship()

    __table_args__ = (UniqueConstraint("lot_id", "user_id", "role", name="uq_lot_user_role"),)


# ───── B2G: workspace для заказчиков ─────


class B2GWorkspace(Base):
    """Workspace заказчика (акимат, школа, больница и т.д.)
    Содержит историю ТЗ и участников.
    """

    __tablename__ = "b2g_workspaces"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # Владелец workspace (создатель)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Название workspace
    name: Mapped[str] = mapped_column(String(255))
    # Реквизиты заказчика
    organization: Mapped[str | None] = mapped_column(String(512), nullable=True)
    organization_bin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    tz_drafts: Mapped[list["B2GTzDraft"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    members: Mapped[list["B2GMember"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class B2GMember(Base):
    """Участник workspace с ролью (multi-user).

    Роли:
    - owner — создатель, может всё
    - editor — может редактировать ТЗ
    - viewer — только просмотр
    """

    __tablename__ = "b2g_members"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("b2g_workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="editor")  # owner / editor / viewer
    invited_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    workspace: Mapped["B2GWorkspace"] = relationship(back_populates="members")

    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_b2g_member"),)


class B2GTzDraft(Base):
    """Черновик ТЗ с историей версий.

    Каждое изменение создаёт новую версию — мы храним всю историю,
    чтобы можно было откатиться или сравнить.
    """

    __tablename__ = "b2g_tz_drafts"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("b2g_workspaces.id", ondelete="CASCADE"), index=True
    )
    # Версия (1, 2, 3...) внутри workspace
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Кто создал эту версию
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Запрос заказчика (свободный текст)
    need_description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Сгенерированное ТЗ (полный JSON от B2GAgent)
    tz_data: Mapped[dict] = mapped_column(JSONType)
    # Метаданные: red_flags, warnings, compliance
    legal_compliance: Mapped[str] = mapped_column(String(32), default="review")
    red_flags_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings_count: Mapped[int] = mapped_column(Integer, default=0)
    # Комментарий к версии
    version_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    workspace: Mapped["B2GWorkspace"] = relationship(back_populates="tz_drafts")

    __table_args__ = (Index("ix_b2g_drafts_ws_version", "workspace_id", "version"),)


# ═══════════════ Supplier Agent (F1–F10, ТЗ docs/tz-supplier-agent.md) ═══════════════
# Архитектурный инвариант: агент умеет только ИСКАТЬ и ГОТОВИТЬ черновики.
# Любой исходящий контакт (письмо/звонок) возможен исключительно через
# approval_queue, и у агента нет инструментов «согласиться / заключить / оплатить».


class CompanyProfile(Base):
    """Профиль компании пользователя (F7).

    Используется для персонализации системного промпта агента и подстановки
    рабочих контактов в исходящие письма/звонки. Контакты НИКОГДА не уходят
    в логи сторонних сервисов.
    """

    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    # Что поставляем / категории (список строк)
    categories: Mapped[list] = mapped_column(JSONType, default=list)
    regions: Mapped[list] = mapped_column(JSONType, default=list)
    # Бюджетная вилка: [min_kzt, max_kzt] или None
    budget_min_kzt: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max_kzt: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_check_kzt: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Производственные мощности / свободный текст
    capabilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Рабочие контакты — только для исходящих
    work_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Режим отправки по умолчанию: review / trusted / manual
    outreach_mode: Mapped[str] = mapped_column(String(16), default="review")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship()


class SupplierAllowlist(Base):
    """Белый список поставщиков — автонастройка разрешена (F7)."""

    __tablename__ = "supplier_allowlist"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    supplier: Mapped[str] = mapped_column(String(256), index=True)
    domain: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "supplier", name="uq_allowlist_user_supplier"),
    )


class SupplierBlocklist(Base):
    """Стоп-лист поставщиков: агент не связывается и не предлагает (F6)."""

    __tablename__ = "supplier_blocklist"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    supplier: Mapped[str] = mapped_column(String(256), index=True)
    domain: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "supplier", name="uq_blocklist_user_supplier"),
    )


class SupplierCandidate(Base):
    """Найденный поставщик с посимвольной сверкой по пунктам ТЗ (F1–F3).

    ``card_json`` — сырая карточка (фото, цена, город, контакты, источники).
    ``match_json`` — статусы по пунктам ТЗ + общий score + предупреждения.
    Общий score вторичен: UI показывает объяснение по пунктам первым (F2).
    """

    __tablename__ = "supplier_candidates"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # lot_id — строка (в т.ч. "raw"/"manual" для файловых анализов)
    lot_id: Mapped[str] = mapped_column(String(64), index=True)
    supplier: Mapped[str] = mapped_column(String(256))
    domain: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    # Карточка: name/price/city/stock/delivery/contacts/sources/image_url
    card_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    # Сверка: requirement_matches[], score, warnings[]
    match_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    score: Mapped[int] = mapped_column(Integer, default=0)
    # Решение пользователя: pending / approved / rejected
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_supplier_candidates_user_lot", "user_id", "lot_id"),
    )


class ApprovalQueue(Base):
    """Очередь на одобрение: черновик письма или план звонка (F3–F5).

    Исходящий контакт разрешён ТОЛЬКО при status=approved (F6, тест в критериях приёмки).
    """

    __tablename__ = "approval_queue"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_candidates.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Тип: email / call
    kind: Mapped[str] = mapped_column(String(16), index=True)
    # Черновик письма (email) либо сценарий/план звонка (call)
    draft_text: Mapped[str] = mapped_column(Text, default="")
    plan_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    # Статус: pending / approved / rejected / executed / failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    decision_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class OutreachJob(Base):
    """Выполненное исходящее действие: письмо или звонок (F4–F5)."""

    __tablename__ = "outreach_jobs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    approval_id: Mapped[int] = mapped_column(
        ForeignKey("approval_queue.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), index=True)
    recipient: Mapped[str] = mapped_column(String(256), default="")
    # Итог переговоров по цене: accept / counter_once / decline
    price_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # Статус: queued / sent / delivered / failed / transcription_ready
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transcription: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PricePolicy(Base):
    """Политика торга пользователя (F6).

    Допуск X% — зона молчаливого согласия. Предел Y% — одна встречная попытка,
    дальше — отказ. Реализуется состояниями в services/price_policy.py,
    а не текстом промпта.
    """

    __tablename__ = "price_policies"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    # X: цена в пределах ±tolerance_pct% — согласиться
    tolerance_pct: Mapped[float] = mapped_column(Float, default=5.0)
    # Y: выше tolerance, но в пределах counter_limit_pct% — одна встречная
    counter_limit_pct: Mapped[float] = mapped_column(Float, default=15.0)
    counter_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class UserInterest(Base):
    """Интересы пользователя для персонализации тендеров (F8).

    Заполняется онбординг-квизом (cold start) и уточняется поведением.
    """

    __tablename__ = "user_interests"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    categories: Mapped[list] = mapped_column(JSONType, default=list)
    regions: Mapped[list] = mapped_column(JSONType, default=list)
    keywords: Mapped[list] = mapped_column(JSONType, default=list)
    min_budget_kzt: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_budget_kzt: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Заполнен ли квиз (cold start закрыт)
    quiz_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TenderFeedback(Base):
    """Обратная связь «подходит / не подходит» — топливо для скоринга v2 (F8)."""

    __tablename__ = "tender_feedback"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    lot_id: Mapped[str] = mapped_column(String(64), index=True)
    # fits / not_fits
    verdict: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class DigestSetting(Base):
    """Настройки дайджеста рекомендаций (F8)."""

    __tablename__ = "digest_settings"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    # Каналы: ["telegram", "email"]
    channels: Mapped[list] = mapped_column(JSONType, default=list)
    # Максимум рекомендаций в день (анти-спам)
    daily_limit: Mapped[int] = mapped_column(Integer, default=5)
    hour_kz: Mapped[int] = mapped_column(Integer, default=9)  # час отправки по Алматы
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AgentAuditLog(Base):
    """Аудит действий агента и расходов (F10, НФТ «наблюдаемость»).

    Пишется на каждый поиск, сверку, черновик, одобрение, письмо, звонок.
    Расходы разделены по типам: llm / tavily / browser / call.
    """

    __tablename__ = "agent_audit_log"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # search / match / draft / decision / email / call / digest
    action: Mapped[str] = mapped_column(String(32), index=True)
    lot_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Произвольные детали (без секретов и контактов третьих лиц)
    detail_json: Mapped[dict] = mapped_column(JSONType, default=dict)
    llm_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tavily_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    browser_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    call_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

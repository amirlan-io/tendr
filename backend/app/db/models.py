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
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    discovery_subs: Mapped[list["DiscoverySubscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
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

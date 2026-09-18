"""Схемы пользователя и квот freemium."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    USER = "user"
    PILOT = "pilot"  # участник пилотной программы (безлимит на 4 мес)
    ADMIN = "admin"


class UserBase(BaseModel):
    telegram_id: int
    username: str | None = None
    full_name: str | None = None
    language: str = "ru"
    role: UserRole = UserRole.USER
    company_bin: str | None = None
    company_name: str | None = None


class UserCreate(UserBase):
    pass


class UserRead(UserBase):
    id: int
    created_at: datetime
    applications_this_month: int = 0
    applications_limit: int = Field(default=3)


class ApplicationRecord(BaseModel):
    """Запись об использовании платформы (для счётчика freemium)."""

    id: int
    user_id: int
    lot_id: str
    created_at: datetime
    kind: str  # "checklist" | "documents" | "legal_check" | "complaint"

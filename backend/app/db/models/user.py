"""Module 1: user and account."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import NOW, TIMESTAMPTZ, Base
from app.db.enums import (
    DIFFICULTY_LEVEL,
    EQUIPMENT_TYPE,
    GOAL_TYPE,
    NOTIFICATION_TYPE,
    SEX_TYPE,
    DifficultyLevel,
    EquipmentType,
    GoalType,
    NotificationType,
    SexType,
)


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    email: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(100))
    surname: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64), server_default=text("'Europe/Warsaw'"))
    registration_date: Mapped[date] = mapped_column(Date, server_default=text("CURRENT_DATE"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class UserProfile(Base):
    __tablename__ = "user_profile"
    __table_args__ = (
        CheckConstraint("age BETWEEN 16 AND 100"),
        CheckConstraint("current_weight BETWEEN 30 AND 300"),
        CheckConstraint("height BETWEEN 120 AND 250"),
        CheckConstraint("activity_level_pal BETWEEN 1.200 AND 2.500"),
        CheckConstraint("target_value BETWEEN 30 AND 300"),
        CheckConstraint("tdee > 0"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    age: Mapped[int] = mapped_column(SmallInteger)
    sex: Mapped[SexType] = mapped_column(SEX_TYPE)
    current_weight: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    height: Mapped[int] = mapped_column(SmallInteger)
    activity_level_pal: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    goal: Mapped[GoalType] = mapped_column(GOAL_TYPE)
    experience_level: Mapped[DifficultyLevel] = mapped_column(DIFFICULTY_LEVEL)
    equipment: Mapped[EquipmentType] = mapped_column(EQUIPMENT_TYPE)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tdee: Mapped[int] = mapped_column(Integer)
    profile_update: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)


class RefreshToken(Base):
    __tablename__ = "refresh_token"
    __table_args__ = (
        CheckConstraint("expires_at > issued_at", name="refresh_token_check"),
        Index("ix_refresh_token_user_id", "user_id"),
        Index("ix_refresh_token_family_id", "family_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    issued_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    replaced_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("refresh_token.id", ondelete="SET NULL")
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_token"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="password_reset_token_check"),
        Index("ix_password_reset_token_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)


class OauthIdentity(Base):
    __tablename__ = "oauth_identity"
    __table_args__ = (
        CheckConstraint("provider IN ('google', 'apple')"),
        UniqueConstraint("provider", "subject"),
        Index("ix_oauth_identity_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(10))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (
        Index("ix_notification_user_id", "user_id"),
        Index("ix_notification_unsent", "scheduled_at", postgresql_where=text("NOT is_sent")),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    message_type: Mapped[NotificationType] = mapped_column(NOTIFICATION_TYPE)
    scheduled_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_sent: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class Reminder(Base):
    __tablename__ = "reminder"
    __table_args__ = (
        CheckConstraint("message_type IN ('meal_reminder', 'training_reminder')"),
        CheckConstraint("day_of_week BETWEEN 1 AND 7"),
        Index("ix_reminder_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    message_type: Mapped[NotificationType] = mapped_column(NOTIFICATION_TYPE)
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger)
    time_of_day: Mapped[time] = mapped_column(Time)
    message: Mapped[str] = mapped_column(String(250))
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class DevicePushToken(Base):
    __tablename__ = "device_push_token"
    __table_args__ = (
        CheckConstraint("platform IN ('android', 'ios')"),
        Index("ix_device_push_token_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(255), unique=True)
    platform: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=NOW)


class Allergen(Base):
    __tablename__ = "allergen"

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    name: Mapped[str] = mapped_column(String(45), unique=True)
    description: Mapped[str] = mapped_column(String(250))


class UserAllergen(Base):
    __tablename__ = "user_allergen"
    __table_args__ = (Index("ix_user_allergen_allergen_id", "allergen_id"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    allergen_id: Mapped[int] = mapped_column(ForeignKey("allergen.id"), primary_key=True)

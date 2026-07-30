"""User ORM model (SRS §18.1)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import AccountStatus, UserRole, as_db_enum


class User(Base):
    """Enterprise customer contact."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    account_status: Mapped[AccountStatus] = mapped_column(
        as_db_enum(AccountStatus, "account_status"),
        default=AccountStatus.ACTIVE,
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        as_db_enum(UserRole, "user_role"), default=UserRole.MEMBER, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

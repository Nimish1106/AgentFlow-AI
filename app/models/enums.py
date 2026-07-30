"""Enumerations shared by ORM models and API schemas (SRS §18, §27)."""

import enum

import sqlalchemy as sa


class AccountStatus(str, enum.Enum):
    """User account status (SRS §18.1)."""

    ACTIVE = "active"
    LOCKED = "locked"
    SUSPENDED = "suspended"


class UserRole(str, enum.Enum):
    """User role (SRS §18.1)."""

    ADMIN = "admin"
    MEMBER = "member"


class SubscriptionPlan(str, enum.Enum):
    """Subscription plan tier (SRS §18.2)."""

    BASIC = "basic"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, enum.Enum):
    """Subscription lifecycle status (SRS §18.2)."""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PaymentStatus(str, enum.Enum):
    """Invoice payment status (SRS §18.3)."""

    PAID = "paid"
    PENDING = "pending"
    DUPLICATE = "duplicate"
    REFUNDED = "refunded"


class TicketPriority(str, enum.Enum):
    """Support ticket priority (SRS §18.4, §27)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketStatus(str, enum.Enum):
    """Support ticket status (SRS §18.4)."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class WorkflowStatus(str, enum.Enum):
    """Workflow run status (SRS §27; superset of §18.5 including 'pending')."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_HITL = "waiting_for_hitl"
    COMPLETED = "completed"
    FAILED = "failed"


def as_db_enum(enum_cls: type[enum.Enum], name: str) -> sa.Enum:
    """Build a SQLAlchemy Enum that stores lowercase string values, not member names."""
    return sa.Enum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
    )

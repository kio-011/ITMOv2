from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("plan IN ('free', 'pro')", name="ck_users_plan"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    default_currency: Mapped[str] = mapped_column(String(3), default="USD")
    plan: Mapped[str] = mapped_column(String(10), default="free", server_default="free")

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="owner")


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_subscriptions_amount_positive"),
        CheckConstraint(
            "billing_cycle IN ('monthly', 'yearly', 'weekly', 'custom_days')",
            name="ck_subscriptions_billing_cycle",
        ),
        CheckConstraint(
            "(billing_cycle = 'custom_days' AND custom_interval_days IS NOT NULL "
            "AND custom_interval_days BETWEEN 1 AND 3650) "
            "OR (billing_cycle <> 'custom_days' AND custom_interval_days IS NULL)",
            name="ck_subscriptions_custom_interval",
        ),
        CheckConstraint(
            "start_date BETWEEN '2000-01-01' AND '2100-12-31' "
            "AND next_billing_date BETWEEN '2000-01-01' AND '2100-12-31'",
            name="ck_subscriptions_dates_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    billing_cycle: Mapped[str] = mapped_column(String(20))
    custom_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    start_date: Mapped[date] = mapped_column(Date, default=date.today)
    next_billing_date: Mapped[date] = mapped_column(Date, default=date.today)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    owner: Mapped["User"] = relationship(back_populates="subscriptions")


class StatementImport(Base):
    __tablename__ = "statement_imports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('analyzed', 'confirmed', 'discarded', 'expired')",
            name="ck_statement_imports_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    encoding: Mapped[str] = mapped_column(String(20))
    delimiter: Mapped[str] = mapped_column(String(4))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default="analyzed")
    ruleset_version: Mapped[str] = mapped_column(String(20))
    rows_total: Mapped[int] = mapped_column(Integer)
    rows_parsed: Mapped[int] = mapped_column(Integer)
    rows_skipped: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    skipped_rows: Mapped[list] = mapped_column(JSON, default=list)
    rejected_groups: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confirm_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirm_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    candidates: Mapped[list["ImportCandidate"]] = relationship(
        back_populates="statement_import", cascade="all, delete-orphan"
    )


class ImportCandidate(Base):
    __tablename__ = "import_candidates"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_import_candidates_amount_positive"),
        CheckConstraint(
            "duplicate_match IN ('none', 'exact', 'amount_differs', 'cycle_differs')",
            name="ck_import_candidates_duplicate_match",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    import_id: Mapped[str] = mapped_column(
        ForeignKey("statement_imports.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    group_key: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    previous_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    billing_cycle: Mapped[str] = mapped_column(String(20))
    custom_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[date] = mapped_column(Date)
    suggested_next_billing_date: Mapped[date] = mapped_column(Date)
    occurrence_count: Mapped[int] = mapped_column(Integer)
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)
    cycle_basis: Mapped[str] = mapped_column(String(20))
    amount_stability: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[int] = mapped_column(Integer)
    confidence_parts: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence_label: Mapped[str] = mapped_column(String(10))
    review: Mapped[bool] = mapped_column(Boolean, default=False)
    preselect_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_match: Mapped[str] = mapped_column(String(20), default="none")
    matched_subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=True
    )
    applied_action: Mapped[str | None] = mapped_column(String(10), nullable=True)
    applied_subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=True
    )

    statement_import: Mapped["StatementImport"] = relationship(
        back_populates="candidates"
    )
    matched_subscription: Mapped["Subscription | None"] = relationship(
        foreign_keys=[matched_subscription_id], lazy="selectin"
    )
    occurrences: Mapped[list["CandidateOccurrence"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="CandidateOccurrence.occurred_on",
    )


class CandidateOccurrence(Base):
    __tablename__ = "candidate_occurrences"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("import_candidates.id", ondelete="CASCADE"), index=True
    )
    line: Mapped[int] = mapped_column(Integer)
    occurred_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    raw_description: Mapped[str] = mapped_column(String(512))

    candidate: Mapped["ImportCandidate"] = relationship(back_populates="occurrences")

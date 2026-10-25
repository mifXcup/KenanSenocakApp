from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class RecordStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    REVERSED = "reversed"


class TrackingMode(str, enum.Enum):
    EXACT = "exact"
    ESTIMATED = "estimated"
    VALUE_ONLY = "value_only"


class MovementType(str, enum.Enum):
    PURCHASE = "purchase"
    USE = "use"
    WASTE = "waste"
    RETURN = "return"
    ADJUSTMENT = "adjustment"


class ExpenseCategory(str, enum.Enum):
    SHIPPING = "shipping"
    INSTALLATION = "installation"
    SITE = "site"
    OTHER = "other"


class EmployeePaymentType(str, enum.Enum):
    ADVANCE = "advance"
    WAGE = "wage"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Supplier(TimestampMixin, Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class Material(TimestampMixin, Base):
    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), nullable=False, unique=True, index=True)
    default_unit: Mapped[str] = mapped_column(String(24), nullable=False)
    tracking_mode: Mapped[TrackingMode] = mapped_column(Enum(TrackingMode), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    contract_amount_kurus: Mapped[int | None] = mapped_column(Integer)
    budget_kurus: Mapped[int | None] = mapped_column(Integer)
    project_state: Mapped[str] = mapped_column(String(32), default="active", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class Purchase(TimestampMixin, Base):
    __tablename__ = "purchases"
    __table_args__ = (
        Index("ix_purchase_supplier_date", "supplier_id", "purchase_date"),
        Index("ix_purchase_project_date", "project_id", "purchase_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    material_id: Mapped[str] = mapped_column(
        ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    unit: Mapped[str | None] = mapped_column(String(24))
    unit_price_kurus: Mapped[int | None] = mapped_column(Integer)
    total_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )

    supplier: Mapped[Supplier] = relationship()
    material: Mapped[Material] = relationship()
    project: Mapped[Project | None] = relationship()


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payment_supplier_date", "supplier_id", "payment_date"),
        Index("ix_payment_purchase_date", "purchase_id", "payment_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    purchase_id: Mapped[str | None] = mapped_column(ForeignKey("purchases.id", ondelete="RESTRICT"))
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MaterialMovement(TimestampMixin, Base):
    __tablename__ = "material_movements"
    __table_args__ = (
        Index("ix_movement_material_date", "material_id", "movement_date"),
        Index("ix_movement_project_date", "project_id", "movement_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    material_id: Mapped[str] = mapped_column(
        ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    purchase_id: Mapped[str | None] = mapped_column(ForeignKey("purchases.id", ondelete="RESTRICT"))
    movement_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType), nullable=False, index=True
    )
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    unit: Mapped[str | None] = mapped_column(String(24))
    amount_kurus: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[TrackingMode] = mapped_column(Enum(TrackingMode), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(80), default="local_user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Employee(TimestampMixin, Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    role: Mapped[str | None] = mapped_column(String(120))
    daily_rate_kurus: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class Site(TimestampMixin, Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    address: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class WorkLog(TimestampMixin, Base):
    __tablename__ = "work_logs"
    __table_args__ = (
        Index("ix_work_log_employee_date", "employee_id", "work_date"),
        Index("ix_work_log_project_date", "project_id", "work_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"))
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class EmployeePayment(TimestampMixin, Base):
    __tablename__ = "employee_payments"
    __table_args__ = (Index("ix_employee_payment_date", "employee_id", "payment_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_type: Mapped[EmployeePaymentType] = mapped_column(
        Enum(EmployeePaymentType), nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class ProjectExpense(TimestampMixin, Base):
    __tablename__ = "project_expenses"
    __table_args__ = (Index("ix_project_expense_date", "project_id", "expense_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"))
    expense_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory), nullable=False)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )

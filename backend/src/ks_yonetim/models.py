from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
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
    # Üye adları en uzun mevcut ad (INSTALLATION, 12) sınırını aşmaz: sütun genişliği değişmez.
    SUBCONTRACT = "subcontract"
    REWORK = "rework"


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
    # customer_name orijinal metin olarak korunur; customer_id normalize edilmiş müşteri kartına bağlar.
    # ALTER ile eklenen sütun-içi REFERENCES için SQLite yansıtması ON DELETE okuyamaz; bu yüzden
    # varsayılan (NO ACTION) kullanılır. Müşteri kartları silinmez, arşivlenir.
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), index=True)
    contract_amount_kurus: Mapped[int | None] = mapped_column(Integer)
    budget_kurus: Mapped[int | None] = mapped_column(Integer)
    project_state: Mapped[str] = mapped_column(String(32), default="active", index=True)
    stage: Mapped[str] = mapped_column(String(32), default="planning", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    accent_color: Mapped[str] = mapped_column(String(16), default="#9A5A3A")
    address: Mapped[str | None] = mapped_column(Text)
    next_step: Mapped[str | None] = mapped_column(String(280))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class ProjectNote(TimestampMixin, Base):
    __tablename__ = "project_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pinned: Mapped[bool] = mapped_column(default=False)
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.ACTIVE)


class ProjectTask(TimestampMixin, Base):
    __tablename__ = "project_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(280), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    task_state: Mapped[str] = mapped_column(String(24), default="todo", index=True)
    waiting_on: Mapped[str | None] = mapped_column(String(180))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.ACTIVE)


class ProjectColor(TimestampMixin, Base):
    __tablename__ = "project_colors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(180), nullable=False)
    color_code: Mapped[str] = mapped_column(String(64), nullable=False)
    material: Mapped[str | None] = mapped_column(String(180))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.ACTIVE)


class ProjectMeasurement(TimestampMixin, Base):
    __tablename__ = "project_measurements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    space_name: Mapped[str] = mapped_column(String(180), nullable=False)
    label: Mapped[str] = mapped_column(String(180), nullable=False)
    value: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="cm")
    measured_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.ACTIVE)


class ProjectVisit(TimestampMixin, Base):
    __tablename__ = "project_visits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    visit_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(280), nullable=False)
    visit_state: Mapped[str] = mapped_column(String(24), default="planned", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.ACTIVE)


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
    # planned | ordered | partially_received | received | cancelled. Eski kayıtlar received sayılır.
    lifecycle_state: Mapped[str] = mapped_column(
        String(24), default="received", server_default="received"
    )
    # Aktif purchase_receipts toplamının önbelleği (aynı transaction'da senkronlanır).
    received_kurus: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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
    # Teslim anında oluşan satın alma hareketi; fiş iptalinde birlikte iptal edilir.
    purchase_receipt_id: Mapped[str | None] = mapped_column(
        ForeignKey("purchase_receipts.id"), index=True
    )
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
    # Eski (v0.2.0) alan: yalnız günlük ücretli personelde current_rate_kurus aynasıdır.
    daily_rate_kurus: Mapped[int | None] = mapped_column(Integer)
    employment_start_date: Mapped[date | None] = mapped_column(Date)
    employment_end_date: Mapped[date | None] = mapped_column(Date)
    employment_state: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active", index=True
    )
    wage_type: Mapped[str] = mapped_column(String(16), default="daily", server_default="daily")
    current_rate_kurus: Mapped[int | None] = mapped_column(Integer)
    iban: Mapped[str | None] = mapped_column(String(34))
    payment_note: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class EmployeeWageRate(TimestampMixin, Base):
    __tablename__ = "employee_wage_rates"
    __table_args__ = (Index("ix_wage_rate_employee_from", "employee_id", "effective_from"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    wage_type: Mapped[str] = mapped_column(String(16), nullable=False)
    rate_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
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
    # hours = normal_hours + overtime_hours, amount_kurus = etkin maliyet (manuel varsa o, yoksa hesap).
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    work_status: Mapped[str] = mapped_column(
        String(16), default="worked", server_default="worked", index=True
    )
    normal_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal(0), server_default="0"
    )
    overtime_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal(0), server_default="0"
    )
    calculated_amount_kurus: Mapped[int | None] = mapped_column(Integer)
    manual_amount_kurus: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
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


class PayrollPeriod(TimestampMixin, Base):
    __tablename__ = "payroll_periods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    # Boşsa ayarlardaki fazla mesai oranı kullanılır.
    overtime_multiplier_percent: Mapped[int | None] = mapped_column(Integer)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class PayrollEntry(TimestampMixin, Base):
    __tablename__ = "payroll_entries"
    __table_args__ = (
        UniqueConstraint("payroll_period_id", "employee_id", name="uq_payroll_entry_employee"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    payroll_period_id: Mapped[str] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    wage_type: Mapped[str] = mapped_column(String(16), nullable=False)
    base_rate_kurus: Mapped[int] = mapped_column(Integer, default=0)
    normal_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal(0))
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal(0))
    worked_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal(0))
    base_earning_kurus: Mapped[int] = mapped_column(Integer, default=0)
    overtime_earning_kurus: Mapped[int] = mapped_column(Integer, default=0)
    bonus_kurus: Mapped[int] = mapped_column(Integer, default=0)
    additional_earning_kurus: Mapped[int] = mapped_column(Integer, default=0)
    deduction_kurus: Mapped[int] = mapped_column(Integer, default=0)
    advance_deduction_kurus: Mapped[int] = mapped_column(Integer, default=0)
    gross_earning_kurus: Mapped[int] = mapped_column(Integer, default=0)
    net_due_kurus: Mapped[int] = mapped_column(Integer, default=0)
    paid_kurus: Mapped[int] = mapped_column(Integer, default=0)
    remaining_kurus: Mapped[int] = mapped_column(Integer, default=0)
    calculation_detail: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class EmployeeFinancialMovement(TimestampMixin, Base):
    __tablename__ = "employee_financial_movements"
    __table_args__ = (
        Index("ix_emp_movement_employee_date", "employee_id", "movement_date"),
        Index("ix_emp_movement_period", "payroll_period_id", "movement_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    payroll_period_id: Mapped[str | None] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="RESTRICT")
    )
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"))
    movement_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # Bir hareket yalnız bir kez terslenebilir: veritabanı düzeyinde benzersizdir.
    reversed_movement_id: Mapped[str | None] = mapped_column(
        ForeignKey("employee_financial_movements.id", ondelete="RESTRICT"), unique=True
    )
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class MlRun(Base):
    __tablename__ = "ml_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_name: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(24), nullable=False)
    trained_from: Mapped[date | None] = mapped_column(Date)
    trained_to: Mapped[date | None] = mapped_column(Date)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    parameters: Mapped[dict | None] = mapped_column(JSON)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class MlPrediction(Base):
    __tablename__ = "ml_predictions"
    __table_args__ = (Index("ix_ml_prediction_entity", "prediction_type", "entity_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ml_run_id: Mapped[str] = mapped_column(
        ForeignKey("ml_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    prediction_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    prediction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    target_date: Mapped[date | None] = mapped_column(Date, index=True)
    predicted_value: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[dict | None] = mapped_column(JSON)
    actual_value: Mapped[float | None] = mapped_column(Float)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_feedback: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    # Türkçe duyarlı, boşlukları sadeleştirilmiş ad; aynı müşteri için tek kart.
    normalized_name: Mapped[str] = mapped_column(
        String(180), nullable=False, unique=True, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    contact_person: Mapped[str | None] = mapped_column(String(180))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class ReceivableSchedule(TimestampMixin, Base):
    """Müşteriden beklenen tahsilat planı; defter hareketi değildir."""

    __tablename__ = "receivable_schedules"
    __table_args__ = (Index("ix_receivable_customer_due", "customer_id", "due_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class CustomerFinancialMovement(TimestampMixin, Base):
    """Değişmez müşteri cari defteri; düzeltme yalnız ters kayıtla yapılır."""

    __tablename__ = "customer_financial_movements"
    __table_args__ = (
        Index("ix_cust_movement_customer_date", "customer_id", "movement_date"),
        Index("ix_cust_movement_project", "project_id", "movement_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    receivable_schedule_id: Mapped[str | None] = mapped_column(
        ForeignKey("receivable_schedules.id", ondelete="RESTRICT"), index=True
    )
    change_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_change_orders.id", ondelete="RESTRICT"), index=True
    )
    movement_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # Bir hareket yalnız bir kez terslenebilir: veritabanı düzeyinde benzersizdir.
    reversed_movement_id: Mapped[str | None] = mapped_column(
        ForeignKey("customer_financial_movements.id", ondelete="RESTRICT"), unique=True
    )
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class ProjectBudgetLine(TimestampMixin, Base):
    __tablename__ = "project_budget_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    # amount_kurus güncel (revize) tutar; original_amount_kurus ilk bütçedir ve değişmez.
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    original_amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class ProjectBudgetRevision(Base):
    __tablename__ = "project_budget_revisions"
    __table_args__ = (
        UniqueConstraint("budget_line_id", "revision_no", name="uq_budget_revision_no"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    budget_line_id: Mapped[str] = mapped_column(
        ForeignKey("project_budget_lines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_amount_kurus: Mapped[int | None] = mapped_column(Integer)
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectChangeOrder(TimestampMixin, Base):
    """Kapsam/bedel değişikliği; yalnız onaylı olanlar revize sözleşme bedeline girer."""

    __tablename__ = "project_change_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Ek iş pozitif, kapsam daraltma negatif olabilir; sıfır anlamsızdır.
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    change_state: Mapped[str] = mapped_column(
        String(16), default="draft", server_default="draft", index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )


class CustomerPaymentAllocation(TimestampMixin, Base):
    """Tahsilatın alacak planına dağıtımı. Çoktan çoğa; iptal fiziksel silme değil durum değişimidir."""

    __tablename__ = "customer_payment_allocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("customer_financial_movements.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    receivable_schedule_id: Mapped[str] = mapped_column(
        ForeignKey("receivable_schedules.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))


class PurchaseReceipt(TimestampMixin, Base):
    """Satın almanın teslim olayı; borç ve maliyet teslim tarihinde ve bu tutarla doğar."""

    __tablename__ = "purchase_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    purchase_id: Mapped[str] = mapped_column(
        ForeignKey("purchases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    amount_kurus: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))


class ProjectCostForecast(Base):
    """Yönetici kalan maliyet tahmini; her değişiklik yeni revizyon satırıdır (ekleme-yalnız)."""

    __tablename__ = "project_cost_forecasts"
    __table_args__ = (
        UniqueConstraint("project_id", "category", "revision_no", name="uq_cost_forecast_revision"),
        Index("ix_cost_forecast_project_category", "project_id", "category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL = manuel tahmin kaldırıldı, otomatik artık hesabına dönüldü.
    remaining_estimate_kurus: Mapped[int | None] = mapped_column(Integer)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    # ACTIVE güncel revizyon, ARCHIVED eski revizyon.
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus), default=RecordStatus.ACTIVE, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

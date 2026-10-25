from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import EmployeePaymentType, ExpenseCategory, MovementType, RecordStatus, TrackingMode


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SupplierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=2000)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_patch(self) -> SupplierUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Firma adı boş bırakılamaz.")
        return self


class SupplierRead(OrmModel):
    id: str
    name: str
    phone: str | None
    note: str | None
    status: RecordStatus
    created_at: datetime


class MaterialCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    default_unit: str = Field(min_length=1, max_length=24)
    tracking_mode: TrackingMode
    note: str | None = Field(default=None, max_length=2000)


class MaterialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    default_unit: str | None = Field(default=None, min_length=1, max_length=24)
    tracking_mode: TrackingMode | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_patch(self) -> MaterialUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        required = {"name", "default_unit", "tracking_mode"}
        for field_name in required & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} boş bırakılamaz.")
        return self


class MaterialRead(OrmModel):
    id: str
    name: str
    default_unit: str
    tracking_mode: TrackingMode
    note: str | None
    status: RecordStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    customer_name: str = Field(min_length=2, max_length=180)
    contract_amount_kurus: int | None = Field(default=None, ge=0)
    budget_kurus: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    customer_name: str | None = Field(default=None, min_length=2, max_length=180)
    contract_amount_kurus: int | None = Field(default=None, ge=0)
    budget_kurus: int | None = Field(default=None, ge=0)
    project_state: Literal["active", "completed", "cancelled"] | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_patch(self) -> ProjectUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        required = {"name", "customer_name", "project_state"}
        for field_name in required & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} boş bırakılamaz.")
        return self


class ProjectRead(OrmModel):
    id: str
    name: str
    customer_name: str
    contract_amount_kurus: int | None
    budget_kurus: int | None
    project_state: str
    status: RecordStatus


class PurchaseCreate(BaseModel):
    supplier_id: str
    material_id: str
    project_id: str | None = None
    purchase_date: date
    due_date: date | None = None
    quantity: Decimal | None = Field(default=None, gt=0, decimal_places=3)
    unit: str | None = Field(default=None, max_length=24)
    unit_price_kurus: int | None = Field(default=None, ge=0)
    total_kurus: int | None = Field(default=None, ge=0)
    paid_kurus: int = Field(default=0, ge=0)
    description: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=80)

    @model_validator(mode="after")
    def validate_amount(self) -> PurchaseCreate:
        calculated: int | None = None
        if self.due_date is not None and self.due_date < self.purchase_date:
            raise ValueError("Vade tarihi satın alma tarihinden önce olamaz.")
        if self.quantity is not None and self.unit_price_kurus is not None:
            calculated = int(
                (self.quantity * self.unit_price_kurus).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            )
        if self.total_kurus is None and calculated is None:
            raise ValueError("Toplam tutar veya miktar ile birim fiyat girilmelidir.")
        if (
            self.total_kurus is not None
            and calculated is not None
            and abs(self.total_kurus - calculated) > 1
        ):
            raise ValueError("Toplam tutar, miktar ve birim fiyat ile uyuşmuyor.")
        resolved = self.total_kurus if self.total_kurus is not None else calculated
        if resolved is not None and self.paid_kurus > resolved:
            raise ValueError("İlk ödeme satın alma toplamını aşamaz.")
        if self.quantity is not None and not self.unit:
            raise ValueError("Miktar girildiğinde birim de girilmelidir.")
        return self

    @property
    def resolved_total_kurus(self) -> int:
        if self.total_kurus is not None:
            return self.total_kurus
        assert self.quantity is not None and self.unit_price_kurus is not None
        return int(
            (self.quantity * self.unit_price_kurus).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )


class PurchaseUpdate(BaseModel):
    project_id: str | None = None
    due_date: date | None = None
    description: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_patch(self) -> PurchaseUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        return self


class PurchaseRead(OrmModel):
    id: str
    supplier_id: str
    material_id: str
    project_id: str | None
    purchase_date: date
    due_date: date | None
    quantity: Decimal | None
    unit: str | None
    unit_price_kurus: int | None
    total_kurus: int
    description: str | None
    status: RecordStatus


class PurchaseDetail(PurchaseRead):
    paid_kurus: int
    remaining_kurus: int


class PaymentCreate(BaseModel):
    supplier_id: str
    purchase_id: str | None = None
    payment_date: date
    amount_kurus: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=80)


class PaymentRead(OrmModel):
    id: str
    supplier_id: str
    purchase_id: str | None
    payment_date: date
    amount_kurus: int
    note: str | None
    status: RecordStatus


class MovementCreate(BaseModel):
    material_id: str
    project_id: str | None = None
    movement_date: date
    movement_type: MovementType
    quantity: Decimal | None = Field(default=None, gt=0, decimal_places=3)
    unit: str | None = Field(default=None, max_length=24)
    amount_kurus: int | None = Field(default=None, ge=0)
    confidence: TrackingMode
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_tracking(self) -> MovementCreate:
        if self.confidence == TrackingMode.VALUE_ONLY and self.amount_kurus is None:
            raise ValueError("Yalnız maliyet kaydında tutar zorunludur.")
        if self.confidence != TrackingMode.VALUE_ONLY and (self.quantity is None or not self.unit):
            raise ValueError("Kesin veya yaklaşık kayıtta miktar ve birim zorunludur.")
        if self.movement_type == MovementType.PURCHASE:
            raise ValueError("Satın alma hareketi satın alma kaydıyla otomatik oluşturulur.")
        return self


class MovementRead(OrmModel):
    id: str
    material_id: str
    project_id: str | None
    movement_date: date
    movement_type: MovementType
    quantity: Decimal | None
    unit: str | None
    amount_kurus: int | None
    confidence: TrackingMode
    status: RecordStatus


class SupplierBalance(BaseModel):
    supplier_id: str
    purchase_total_kurus: int
    payment_total_kurus: int
    remaining_kurus: int


class MaterialBalance(BaseModel):
    material_id: str
    estimated_quantity: Decimal | None
    unit: str
    confidence: TrackingMode
    warning: str | None = None


class AgingBucket(BaseModel):
    key: str
    label: str
    amount_kurus: int
    count: int


class AgingItem(BaseModel):
    purchase_id: str
    supplier_id: str
    supplier_name: str
    material_name: str
    purchase_date: date
    due_date: date | None
    total_kurus: int
    remaining_kurus: int
    days_overdue: int | None
    bucket: str


class AgingSupplier(BaseModel):
    supplier_id: str
    supplier_name: str
    total_open_kurus: int
    overdue_kurus: int
    credit_kurus: int
    buckets: dict[str, int]


class DebtAgingReport(BaseModel):
    as_of: date
    total_open_kurus: int
    overdue_kurus: int
    credit_kurus: int
    buckets: list[AgingBucket]
    suppliers: list[AgingSupplier]
    items: list[AgingItem]


class SupplierReportRow(BaseModel):
    supplier_id: str
    supplier_name: str
    purchase_count: int
    purchase_total_kurus: int
    payment_total_kurus: int
    current_debt_kurus: int


class MaterialReportRow(BaseModel):
    material_id: str
    material_name: str
    unit: str | None
    purchase_count: int
    quantity: Decimal | None
    total_kurus: int


class MonthReportRow(BaseModel):
    month: str
    purchase_count: int
    total_kurus: int


class PurchaseReport(BaseModel):
    date_from: date | None
    date_to: date | None
    purchase_count: int
    purchase_total_kurus: int
    payment_total_kurus: int
    by_supplier: list[SupplierReportRow]
    by_material: list[MaterialReportRow]
    by_month: list[MonthReportRow]


class DashboardSummary(BaseModel):
    active_project_count: int
    supplier_count: int
    purchase_total_kurus: int
    payment_total_kurus: int
    supplier_debt_kurus: int


class BackupRead(BaseModel):
    backup_id: str
    kind: str
    created_at: datetime
    size_bytes: int
    sha256: str
    app_version: str
    integrity: str


class BackupStatus(BaseModel):
    healthy: bool
    in_progress: bool
    last_error: str | None
    backup_count: int
    latest_backup: BackupRead | None
    latest_automatic: BackupRead | None
    automatic_retention: int


class BackupRestoreResult(BaseModel):
    restored_backup: BackupRead
    pre_restore_backup: BackupRead
    restart_required: bool = True


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=120)
    daily_rate_kurus: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)


class EmployeeRead(OrmModel):
    id: str
    name: str
    phone: str | None
    role: str | None
    daily_rate_kurus: int | None
    note: str | None
    status: RecordStatus


class SiteCreate(BaseModel):
    project_id: str | None = None
    name: str = Field(min_length=2, max_length=180)
    address: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)


class SiteRead(OrmModel):
    id: str
    project_id: str | None
    name: str
    address: str | None
    note: str | None
    status: RecordStatus


class WorkLogCreate(BaseModel):
    employee_id: str
    project_id: str | None = None
    site_id: str | None = None
    work_date: date
    hours: Decimal = Field(gt=0, le=24, decimal_places=2)
    amount_kurus: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)


class WorkLogRead(OrmModel):
    id: str
    employee_id: str
    project_id: str | None
    site_id: str | None
    work_date: date
    hours: Decimal
    amount_kurus: int
    note: str | None
    status: RecordStatus


class EmployeePaymentCreate(BaseModel):
    employee_id: str
    payment_date: date
    amount_kurus: int = Field(gt=0)
    payment_type: EmployeePaymentType
    note: str | None = Field(default=None, max_length=2000)


class EmployeePaymentRead(OrmModel):
    id: str
    employee_id: str
    payment_date: date
    amount_kurus: int
    payment_type: EmployeePaymentType
    note: str | None
    status: RecordStatus


class ProjectExpenseCreate(BaseModel):
    project_id: str
    site_id: str | None = None
    expense_date: date
    category: ExpenseCategory
    amount_kurus: int = Field(gt=0)
    description: str | None = Field(default=None, max_length=2000)


class ProjectExpenseRead(OrmModel):
    id: str
    project_id: str
    site_id: str | None
    expense_date: date
    category: ExpenseCategory
    amount_kurus: int
    description: str | None
    status: RecordStatus


class ProjectCostSummary(BaseModel):
    project_id: str
    purchase_kurus: int
    labor_kurus: int
    shipping_kurus: int
    installation_kurus: int
    site_kurus: int
    other_kurus: int
    total_cost_kurus: int
    budget_kurus: int | None
    budget_variance_kurus: int | None
    contract_amount_kurus: int | None
    estimated_profit_kurus: int | None

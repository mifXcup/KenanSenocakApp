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
    # Verilirse müşteri kartı esas alınır ve customer_name karttaki adla eşitlenir.
    customer_id: str | None = None
    contract_amount_kurus: int | None = Field(default=None, ge=0)
    budget_kurus: int | None = Field(default=None, ge=0)
    stage: Literal["planning", "design", "approval", "production", "delivery", "installation", "completed"] = "planning"
    progress_percent: int = Field(default=0, ge=0, le=100)
    accent_color: str = Field(default="#9A5A3A", min_length=4, max_length=16)
    address: str | None = Field(default=None, max_length=2000)
    next_step: str | None = Field(default=None, max_length=280)
    note: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    customer_name: str | None = Field(default=None, min_length=2, max_length=180)
    customer_id: str | None = None
    contract_amount_kurus: int | None = Field(default=None, ge=0)
    budget_kurus: int | None = Field(default=None, ge=0)
    project_state: Literal["active", "completed", "cancelled"] | None = None
    stage: Literal["planning", "design", "approval", "production", "delivery", "installation", "completed"] | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    accent_color: str | None = Field(default=None, min_length=4, max_length=16)
    address: str | None = Field(default=None, max_length=2000)
    next_step: str | None = Field(default=None, max_length=280)
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
    customer_id: str | None = None
    contract_amount_kurus: int | None
    budget_kurus: int | None
    project_state: str
    stage: str
    progress_percent: int
    accent_color: str
    address: str | None
    next_step: str | None
    note: str | None
    status: RecordStatus


class ProjectNoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    pinned: bool = False


class ProjectNoteRead(OrmModel):
    id: str
    project_id: str
    content: str
    pinned: bool
    created_at: datetime


class ProjectTaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=280)
    due_date: date | None = None
    task_state: Literal["todo", "waiting", "done"] = "todo"
    waiting_on: str | None = Field(default=None, max_length=180)
    note: str | None = Field(default=None, max_length=2000)


class ProjectTaskUpdate(BaseModel):
    task_state: Literal["todo", "waiting", "done"]


class ProjectTaskRead(OrmModel):
    id: str
    project_id: str
    title: str
    due_date: date | None
    task_state: str
    waiting_on: str | None
    note: str | None
    created_at: datetime


class ProjectColorCreate(BaseModel):
    label: str = Field(min_length=2, max_length=180)
    color_code: str = Field(min_length=2, max_length=64)
    material: str | None = Field(default=None, max_length=180)
    note: str | None = Field(default=None, max_length=2000)


class ProjectColorRead(OrmModel):
    id: str
    project_id: str
    label: str
    color_code: str
    material: str | None
    note: str | None
    created_at: datetime


class ProjectMeasurementCreate(BaseModel):
    space_name: str = Field(min_length=2, max_length=180)
    label: str = Field(min_length=2, max_length=180)
    value: str = Field(min_length=1, max_length=80)
    unit: str = Field(default="cm", min_length=1, max_length=24)
    measured_on: date
    note: str | None = Field(default=None, max_length=2000)


class ProjectMeasurementRead(OrmModel):
    id: str
    project_id: str
    space_name: str
    label: str
    value: str
    unit: str
    measured_on: date
    note: str | None
    created_at: datetime


class ProjectVisitCreate(BaseModel):
    visit_date: date
    purpose: str = Field(min_length=2, max_length=280)
    visit_state: Literal["planned", "completed", "cancelled"] = "planned"
    note: str | None = Field(default=None, max_length=2000)


class ProjectVisitRead(OrmModel):
    id: str
    project_id: str
    visit_date: date
    purpose: str
    visit_state: str
    note: str | None
    created_at: datetime


class ProjectHubRead(BaseModel):
    project: ProjectRead
    notes: list[ProjectNoteRead]
    tasks: list[ProjectTaskRead]
    colors: list[ProjectColorRead]
    measurements: list[ProjectMeasurementRead]
    visits: list[ProjectVisitRead]


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
    # Yeni kayıt varsayılanı received: eski istemciler davranışı değişmeden kullanır.
    lifecycle_state: Literal["planned", "ordered", "received"] = "received"

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
    lifecycle_state: str = "received"
    received_kurus: int = 0


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
    schema_revision: str | None = None


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


WageType = Literal["monthly", "daily", "hourly"]
EmploymentState = Literal["active", "inactive", "left"]
DEFAULT_RATE_START = date(2000, 1, 1)


def _clean_iban(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = "".join(value.split()).upper()
    if not cleaned:
        return None
    if not cleaned.isalnum() or not 15 <= len(cleaned) <= 34:
        raise ValueError("IBAN 15–34 karakterli harf/rakam dizisi olmalıdır.")
    return cleaned


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=120)
    daily_rate_kurus: int | None = Field(default=None, ge=0)
    wage_type: WageType | None = None
    current_rate_kurus: int | None = Field(default=None, ge=0)
    rate_effective_from: date | None = None
    employment_start_date: date | None = None
    employment_end_date: date | None = None
    employment_state: EmploymentState = "active"
    iban: str | None = Field(default=None, max_length=48)
    payment_note: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    email: str | None = Field(default=None, max_length=180)
    address: str | None = Field(default=None, max_length=2000)
    skill: str | None = Field(default=None, max_length=120)
    emergency_contact_name: str | None = Field(default=None, max_length=180)
    emergency_contact_phone: str | None = Field(default=None, max_length=40)
    emergency_contact_relation: str | None = Field(default=None, max_length=60)
    payment_method: PaymentMethod | None = None
    salary_day: int | None = Field(default=None, ge=1, le=31)

    @model_validator(mode="after")
    def validate_employee(self) -> EmployeeCreate:
        if self.daily_rate_kurus is not None:
            if self.wage_type not in (None, "daily"):
                raise ValueError("daily_rate_kurus yalnız günlük ücretle kullanılabilir.")
            if self.current_rate_kurus not in (None, self.daily_rate_kurus):
                raise ValueError("daily_rate_kurus ve current_rate_kurus uyuşmuyor.")
            self.wage_type = "daily"
            self.current_rate_kurus = self.daily_rate_kurus
        if (
            self.employment_start_date
            and self.employment_end_date
            and self.employment_end_date < self.employment_start_date
        ):
            raise ValueError("İşten ayrılış tarihi başlangıçtan önce olamaz.")
        self.iban = _clean_iban(self.iban)
        return self


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=120)
    employment_start_date: date | None = None
    employment_end_date: date | None = None
    employment_state: EmploymentState | None = None
    iban: str | None = Field(default=None, max_length=48)
    payment_note: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
    email: str | None = Field(default=None, max_length=180)
    address: str | None = Field(default=None, max_length=2000)
    skill: str | None = Field(default=None, max_length=120)
    emergency_contact_name: str | None = Field(default=None, max_length=180)
    emergency_contact_phone: str | None = Field(default=None, max_length=40)
    emergency_contact_relation: str | None = Field(default=None, max_length=60)
    payment_method: PaymentMethod | None = None
    salary_day: int | None = Field(default=None, ge=1, le=31)

    @model_validator(mode="after")
    def validate_patch(self) -> EmployeeUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        for field_name in {"name", "employment_state"} & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} boş bırakılamaz.")
        if "iban" in self.model_fields_set:
            self.iban = _clean_iban(self.iban)
        return self


class EmployeeRead(OrmModel):
    id: str
    name: str
    phone: str | None
    role: str | None
    daily_rate_kurus: int | None
    wage_type: str
    current_rate_kurus: int | None
    employment_start_date: date | None
    employment_end_date: date | None
    employment_state: str
    iban: str | None
    payment_note: str | None
    note: str | None
    email: str | None = None
    address: str | None = None
    skill: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    emergency_contact_relation: str | None = None
    payment_method: str | None = None
    salary_day: int | None = None
    status: RecordStatus


class WageRateCreate(BaseModel):
    effective_from: date
    effective_to: date | None = None
    wage_type: WageType
    rate_kurus: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_range(self) -> WageRateCreate:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("Bitiş tarihi başlangıçtan önce olamaz.")
        return self


class WageRateRead(OrmModel):
    id: str
    employee_id: str
    effective_from: date
    effective_to: date | None
    wage_type: str
    rate_kurus: int
    reason: str | None
    status: RecordStatus
    created_at: datetime
    updated_at: datetime


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


class ImportIssue(BaseModel):
    row: int
    field: str | None = None
    message: str


# Yıllık/raporlu/mazeret izin durumları yalnız izin talebi onayıyla üretilir; elle girilemez.
WorkStatus = Literal[
    "worked",
    "half_day",
    "overtime",
    "paid_leave",
    "unpaid_leave",
    "absent",
    "public_holiday",
    "weekly_rest",
]
PaymentMethod = Literal["cash", "bank_transfer", "other"]


class WorkLogCreate(BaseModel):
    employee_id: str
    project_id: str | None = None
    site_id: str | None = None
    work_date: date
    work_status: WorkStatus = "worked"
    normal_hours: Decimal | None = Field(default=None, ge=0, le=24, decimal_places=2)
    overtime_hours: Decimal = Field(default=Decimal(0), ge=0, le=24, decimal_places=2)
    manual_amount_kurus: int | None = Field(default=None, ge=0)
    # v0.2.0 istemcileri için eski alanlar: hours -> normal_hours, amount_kurus -> manuel tutar.
    hours: Decimal | None = Field(default=None, gt=0, le=24, decimal_places=2)
    amount_kurus: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def merge_legacy_fields(self) -> WorkLogCreate:
        if self.hours is not None:
            if self.normal_hours not in (None, self.hours):
                raise ValueError("hours ve normal_hours uyuşmuyor.")
            self.normal_hours = self.hours
        if self.amount_kurus is not None:
            if self.manual_amount_kurus not in (None, self.amount_kurus):
                raise ValueError("amount_kurus ve manual_amount_kurus uyuşmuyor.")
            self.manual_amount_kurus = self.amount_kurus
        return self


class WorkLogUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_date: date | None = None
    work_status: WorkStatus | None = None
    normal_hours: Decimal | None = Field(default=None, ge=0, le=24, decimal_places=2)
    overtime_hours: Decimal | None = Field(default=None, ge=0, le=24, decimal_places=2)
    project_id: str | None = None
    site_id: str | None = None
    manual_amount_kurus: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_patch(self) -> WorkLogUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        if "work_date" in self.model_fields_set and self.work_date is None:
            raise ValueError("work_date boş bırakılamaz.")
        if "work_status" in self.model_fields_set and self.work_status is None:
            raise ValueError("work_status boş bırakılamaz.")
        return self


class WorkLogRead(OrmModel):
    id: str
    employee_id: str
    project_id: str | None
    site_id: str | None
    work_date: date
    work_status: str
    normal_hours: Decimal
    overtime_hours: Decimal
    hours: Decimal
    amount_kurus: int
    calculated_amount_kurus: int | None
    manual_amount_kurus: int | None
    leave_request_id: str | None = None
    leave_hours: Decimal | None = None
    source: str = "manual"
    note: str | None
    status: RecordStatus


class LaborSettingsRead(BaseModel):
    overtime_multiplier_percent: int
    standard_day_hours: int


class LaborSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overtime_multiplier_percent: int | None = Field(default=None, ge=100, le=500)
    standard_day_hours: int | None = Field(default=None, ge=1, le=24)

    @model_validator(mode="after")
    def validate_patch(self) -> LaborSettingsUpdate:
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("En az bir ayar geçerli bir değerle gönderilmelidir.")
        return self


class WorkLogImportPreview(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    total_labor_kurus: int
    issues: list[ImportIssue]
    duplicates: list[ImportIssue]
    sample: list[dict]


class WorkLogImportResult(BaseModel):
    created: int
    skipped_duplicates: int
    total_labor_kurus: int
    backup_id: str


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


class SpreadsheetFilePayload(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=8)


class SpreadsheetFileResponse(BaseModel):
    file_name: str
    mime_type: str
    content_base64: str


class ImportPreview(BaseModel):
    kind: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    issues: list[ImportIssue]
    sample: list[dict]


class ImportCommitResult(BaseModel):
    kind: str
    created: int
    skipped_duplicates: int
    backup_id: str


class MLStatus(BaseModel):
    ready: bool
    purchase_count: int
    material_series_ready: int
    reorder_series_ready: int
    project_series_ready: int
    minimum_price_samples: int
    minimum_reorder_samples: int
    message: str


class PriceAnomaly(BaseModel):
    material_id: str
    material_name: str
    unit: str
    sample_count: int
    latest_date: date
    latest_unit_price_kurus: int
    expected_unit_price_kurus: int
    deviation_percent: float
    anomaly_score: float
    is_anomaly: bool
    next_expected_unit_price_kurus: int


class ReorderForecast(BaseModel):
    material_id: str
    material_name: str
    sample_count: int
    median_interval_days: int
    next_expected_date: date
    days_until_expected: int
    confidence: str


class ProjectRisk(BaseModel):
    project_id: str
    project_name: str
    sample_count: int
    current_cost_kurus: int
    budget_kurus: int
    projected_30d_cost_kurus: int
    budget_usage_percent: float
    projected_usage_percent: float
    risk_level: str


class MLInsights(BaseModel):
    as_of: date
    status: MLStatus
    price_anomalies: list[PriceAnomaly]
    reorder_forecasts: list[ReorderForecast]
    project_risks: list[ProjectRisk]

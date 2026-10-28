"""Maaş dönemleri: deterministik hesap, kesinleştirme (yedekli) ve kapatma.

Bu sistem resmî bordro/SGK/vergi hesabı yapmaz; işletme içi maaş ve borç takibidir.

Hesap kuralları (calculation_detail.rules içinde de yazılıdır):
- daily: günlük ücret × normal saat / standart gün saati (kayıt yoksa ödeme yok).
- hourly: saatlik ücret × normal saat.
- monthly: dönemdeki her takvim günü için aylık ücret / o ayın gün sayısı (tam takvim ayı tam aylık ücrettir).
  Ücretsiz izin ve devamsızlık kayıtları o günün değerini düşer; kaydı olmayan günler çalışıldı sayılır.
- fazla mesai: saatlik karşılık × fazla mesai saati × oran (dönem veya ayar), tüm ücret türlerinde.
- manuel tutarlı puantaj (günlük/saatlik): manuel tutar o günün tamamı olarak taban kazanca yazılır.
- yuvarlama: tüm Decimal toplamlar bileşen başına bir kez ROUND_HALF_UP ile kuruşa yuvarlanır.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_sidecar_token
from .attendance import assert_attendance_complete
from .backup import BackupError, backup_manager
from .database import get_session
from .exports import Column, ReportTable, pdf_response, xlsx_response
from .labor_cost import (
    PAID_STATUSES,
    UNPAID_STATUSES,
    LaborSettings,
    daily_equivalent,
    hourly_equivalent,
    load_settings,
    overtime_pay,
    to_kurus,
)
from .models import Employee, PayrollEntry, PayrollPeriod, RecordStatus, WorkLog
from .schemas import OrmModel
from .wages import RateBook, load_rate_book

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])

RULES = {
    "monthly": "takvim günü başına aylık/gün sayısı; ücretsiz izin ve devamsızlık günü düşer",
    "daily": "günlük ücret × normal saat / standart gün saati",
    "hourly": "saatlik ücret × normal saat",
    "overtime": "saatlik karşılık × fazla mesai saati × oran",
    "rounding": "bileşen başına ROUND_HALF_UP",
}
ENTRY_FIELDS = (
    "wage_type",
    "base_rate_kurus",
    "normal_hours",
    "overtime_hours",
    "worked_days",
    "base_earning_kurus",
    "overtime_earning_kurus",
    "bonus_kurus",
    "additional_earning_kurus",
    "deduction_kurus",
    "advance_deduction_kurus",
    "gross_earning_kurus",
    "net_due_kurus",
)


class PeriodCreate(BaseModel):
    period_start: date
    period_end: date
    title: str | None = Field(default=None, min_length=2, max_length=180)
    overtime_multiplier_percent: int | None = Field(default=None, ge=100, le=500)

    @model_validator(mode="after")
    def validate_range(self) -> PeriodCreate:
        if self.period_end < self.period_start:
            raise ValueError("Dönem bitişi başlangıçtan önce olamaz.")
        if (self.period_end - self.period_start).days > 365:
            raise ValueError("Bir maaş dönemi en fazla 366 gün olabilir.")
        return self


class PeriodRead(OrmModel):
    id: str
    period_start: date
    period_end: date
    title: str
    state: str
    overtime_multiplier_percent: int | None
    calculated_at: datetime | None
    finalized_at: datetime | None
    closed_at: datetime | None
    status: RecordStatus
    created_at: datetime
    updated_at: datetime


class PeriodDetail(PeriodRead):
    entry_count: int
    totals: dict[str, int]


class EntryRead(OrmModel):
    id: str
    payroll_period_id: str
    employee_id: str
    employee_name: str | None = None
    wage_type: str
    base_rate_kurus: int
    normal_hours: Decimal
    overtime_hours: Decimal
    worked_days: Decimal
    base_earning_kurus: int
    overtime_earning_kurus: int
    bonus_kurus: int
    additional_earning_kurus: int
    deduction_kurus: int
    advance_deduction_kurus: int
    gross_earning_kurus: int
    net_due_kurus: int
    paid_kurus: int
    remaining_kurus: int
    calculation_detail: dict | None
    status: RecordStatus


class CalculateRequest(BaseModel):
    auto_advance_deduction: bool = True
    advance_deductions: dict[str, int] = Field(default_factory=dict)


class FinalizeRequest(BaseModel):
    payment_due_date: date | None = None


class CloseRequest(BaseModel):
    allow_unpaid: bool = False


# --- Defter bağlantıları (finance.py tarafından doldurulur) ----------------------------------------


def gather_inputs(session: Session, period: PayrollPeriod) -> dict[str, dict[str, int]]:
    """employee_id -> {bonus, additional, deduction} (dönem girdi hareketleri)."""
    return {}


def advance_pools(session: Session, employee_ids: list[str], as_of: date) -> dict[str, int]:
    """employee_id -> kalan avans bakiyesi."""
    return {}


def post_finalize_ledger(
    session: Session, period: PayrollPeriod, entries: list[PayrollEntry], due_date: date | None
) -> None:
    return None


def refresh_entry_balances(session: Session, period: PayrollPeriod) -> None:
    for entry in session.scalars(
        select(PayrollEntry).where(PayrollEntry.payroll_period_id == period.id)
    ):
        entry.remaining_kurus = entry.net_due_kurus - entry.paid_kurus


# --- Hesap --------------------------------------------------------------------------------------


def _period_days(period: PayrollPeriod) -> list[date]:
    return [
        period.period_start + timedelta(days=offset)
        for offset in range((period.period_end - period.period_start).days + 1)
    ]


def _unpaid_fraction(log: WorkLog, settings: LaborSettings) -> Decimal:
    """Kısmi (yarım gün/saatlik) ücretsiz izinde günün yalnız izin saati kadarı düşülür."""
    if log.leave_hours and log.leave_hours > 0 and log.normal_hours > 0:
        return min(Decimal(1), Decimal(log.leave_hours) / settings.standard_day_hours)
    return Decimal(1)


def compute_employee(
    employee: Employee,
    logs: dict[date, WorkLog],
    days: list[date],
    book: RateBook,
    settings: LaborSettings,
    multiplier: int,
    inputs: dict[str, int],
    advance_pool: int,
    advance_override: int | None,
    auto_advance: bool,
) -> dict | None:
    start, end = employee.employment_start_date, employee.employment_end_date
    base_exact = Decimal(0)  # monthly + hourly/daily hesaplanan
    manual_total = 0
    overtime_exact = Decimal(0)
    unpaid_exact = Decimal(0)
    normal_hours = overtime_hours = worked_days = Decimal(0)
    unpaid_days = 0
    manual_logs = 0
    missing_rate_days: list[str] = []
    last_rate = None
    employed_days_with_rate = 0

    for day in days:
        log = logs.get(day)
        # Kısmi ücretsiz izin gününde çalışılan saatler (normal_hours > 0) ücretlendirilir.
        paid_log = log is not None and (
            log.work_status in PAID_STATUSES
            or (log.work_status in UNPAID_STATUSES and log.normal_hours > 0)
        )
        in_window = (start is None or day >= start) and (end is None or day <= end)
        rate = book.at(employee.id, day)
        if rate is None:
            if paid_log:
                missing_rate_days.append(day.isoformat())
            continue
        if rate.wage_type == "monthly" and not in_window and log is None:
            continue
        last_rate = rate
        if rate.wage_type == "monthly":
            if not in_window:
                continue
            employed_days_with_rate += 1
            value = daily_equivalent(rate.rate_kurus, "monthly", day, settings)
            base_exact += value
            if log is not None and log.work_status in UNPAID_STATUSES:
                unpaid_exact += value * _unpaid_fraction(log, settings)
                unpaid_days += 1
        elif not paid_log:
            continue
        else:
            employed_days_with_rate += 1
            assert log is not None
            if log.manual_amount_kurus is not None:
                manual_total += log.manual_amount_kurus
                manual_logs += 1
            else:
                base_exact += hourly_equivalent(
                    rate.rate_kurus, rate.wage_type, day, settings
                ) * log.normal_hours
        if paid_log:
            assert log is not None
            normal_hours += log.normal_hours
            overtime_hours += log.overtime_hours
            worked_days += log.normal_hours / settings.standard_day_hours
            manual_replaces = log.manual_amount_kurus is not None and rate.wage_type != "monthly"
            if log.overtime_hours > 0 and not manual_replaces:
                overtime_exact += overtime_pay(
                    rate.rate_kurus, rate.wage_type, day, log.overtime_hours, settings, multiplier
                )

    bonus = inputs.get("bonus", 0)
    additional = inputs.get("additional", 0)
    deduction = inputs.get("deduction", 0)
    if last_rate is None and not (bonus or additional or deduction) and not logs:
        return None
    if employed_days_with_rate == 0 and not logs and not (bonus or additional or deduction):
        return None

    base = to_kurus(base_exact - unpaid_exact) + manual_total
    overtime = to_kurus(overtime_exact)
    gross = base + overtime + bonus + additional
    room = max(0, gross - deduction)
    warnings: list[str] = []
    if deduction > gross:
        warnings.append("deduction_exceeds_gross")
    if missing_rate_days:
        warnings.append("missing_rate_days")
    wanted = advance_override if advance_override is not None else (advance_pool if auto_advance else 0)
    advance = max(0, min(wanted, advance_pool, room))
    net = room - advance
    return {
        "employee_id": employee.id,
        "wage_type": last_rate.wage_type if last_rate else employee.wage_type,
        "base_rate_kurus": last_rate.rate_kurus if last_rate else 0,
        "normal_hours": normal_hours.quantize(Decimal("0.01")),
        "overtime_hours": overtime_hours.quantize(Decimal("0.01")),
        "worked_days": worked_days.quantize(Decimal("0.01")),
        "base_earning_kurus": base,
        "overtime_earning_kurus": overtime,
        "bonus_kurus": bonus,
        "additional_earning_kurus": additional,
        "deduction_kurus": deduction,
        "advance_deduction_kurus": advance,
        "gross_earning_kurus": gross,
        "net_due_kurus": net,
        "calculation_detail": {
            "version": 1,
            "rules": RULES,
            "settings": {**settings.as_dict(), "overtime_multiplier_percent": multiplier},
            "unpaid_days": unpaid_days,
            "unpaid_deduction_kurus": to_kurus(unpaid_exact),
            "manual_amount_logs": manual_logs,
            "manual_amount_kurus": manual_total,
            "advance_pool_kurus": advance_pool,
            "excess_deduction_kurus": max(0, deduction - gross),
            "missing_rate_days": missing_rate_days,
            "warnings": warnings,
        },
    }


def compute_period(
    session: Session, period: PayrollPeriod, request: CalculateRequest
) -> list[dict]:
    settings = load_settings(session)
    multiplier = period.overtime_multiplier_percent or settings.overtime_multiplier_percent
    days = _period_days(period)
    logs: dict[str, dict[date, WorkLog]] = defaultdict(dict)
    for log in session.scalars(
        select(WorkLog).where(
            WorkLog.status == RecordStatus.ACTIVE,
            WorkLog.work_date >= period.period_start,
            WorkLog.work_date <= period.period_end,
        )
    ):
        logs[log.employee_id][log.work_date] = log
    inputs = gather_inputs(session, period)
    employees = session.scalars(
        select(Employee).where(
            Employee.status != RecordStatus.CANCELLED,
            or_(
                Employee.id.in_(list(logs) + list(inputs)),
                (Employee.status == RecordStatus.ACTIVE)
                & (
                    Employee.employment_start_date.is_(None)
                    | (Employee.employment_start_date <= period.period_end)
                )
                & (
                    Employee.employment_end_date.is_(None)
                    | (Employee.employment_end_date >= period.period_start)
                ),
            ),
        )
    ).all()
    employees = sorted(employees, key=lambda e: (e.name.casefold(), e.id))
    ids = [e.id for e in employees]
    book = load_rate_book(session, ids)
    pools = advance_pools(session, ids, period.period_end)
    output: list[dict] = []
    for employee in employees:
        entry = compute_employee(
            employee,
            logs.get(employee.id, {}),
            days,
            book,
            settings,
            multiplier,
            inputs.get(employee.id, {}),
            pools.get(employee.id, 0),
            request.advance_deductions.get(employee.id),
            request.auto_advance_deduction,
        )
        if entry is not None:
            output.append(entry)
    return output


def signature(item: dict | PayrollEntry) -> tuple:
    getter = item.get if isinstance(item, dict) else lambda key: getattr(item, key)
    return tuple(
        Decimal(getter(field)).quantize(Decimal("0.01"))
        if field.endswith("hours") or field == "worked_days"
        else getter(field)
        for field in ENTRY_FIELDS
    )


# --- Yardımcılar ----------------------------------------------------------------------------------


def get_period(session: Session, period_id: str) -> PayrollPeriod:
    period = session.get(PayrollPeriod, period_id)
    if period is None or period.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "Maaş dönemi bulunamadı.", 404)
    return period


def period_totals(session: Session, period_id: str) -> tuple[int, dict[str, int]]:
    columns = {
        "base_earning_kurus": PayrollEntry.base_earning_kurus,
        "overtime_earning_kurus": PayrollEntry.overtime_earning_kurus,
        "bonus_kurus": PayrollEntry.bonus_kurus,
        "additional_earning_kurus": PayrollEntry.additional_earning_kurus,
        "deduction_kurus": PayrollEntry.deduction_kurus,
        "advance_deduction_kurus": PayrollEntry.advance_deduction_kurus,
        "gross_earning_kurus": PayrollEntry.gross_earning_kurus,
        "net_due_kurus": PayrollEntry.net_due_kurus,
        "paid_kurus": PayrollEntry.paid_kurus,
        "remaining_kurus": PayrollEntry.remaining_kurus,
    }
    row = session.execute(
        select(
            func.count(PayrollEntry.id),
            *[func.coalesce(func.sum(column), 0) for column in columns.values()],
        ).where(
            PayrollEntry.payroll_period_id == period_id,
            PayrollEntry.status == RecordStatus.ACTIVE,
        )
    ).one()
    return int(row[0]), {key: int(value) for key, value in zip(columns, row[1:], strict=True)}


def serialize_entries(session: Session, entries: list[PayrollEntry]) -> list[EntryRead]:
    names = dict(
        session.execute(
            select(Employee.id, Employee.name).where(
                Employee.id.in_([e.employee_id for e in entries])
            )
        ).all()
    ) if entries else {}
    output = []
    for entry in entries:
        read = EntryRead.model_validate(entry)
        read.employee_name = names.get(entry.employee_id)
        output.append(read)
    return output


def _detail(session: Session, period: PayrollPeriod) -> PeriodDetail:
    count, totals = period_totals(session, period.id)
    return PeriodDetail(
        **PeriodRead.model_validate(period).model_dump(), entry_count=count, totals=totals
    )


# --- Uç noktalar ------------------------------------------------------------------------------------


@router.post("/payroll-periods", response_model=PeriodDetail, status_code=201)
def create_period(payload: PeriodCreate, session: Session = Depends(get_session)):
    overlap = session.scalars(
        select(PayrollPeriod).where(
            PayrollPeriod.status == RecordStatus.ACTIVE,
            PayrollPeriod.period_start <= payload.period_end,
            PayrollPeriod.period_end >= payload.period_start,
        )
    ).first()
    if overlap:
        raise ApiError(
            "payroll_period_overlap",
            "Maaş dönemi mevcut bir dönemle tarih olarak çakışıyor.",
            409,
            {"payroll_period_id": overlap.id, "title": overlap.title},
        )
    period = PayrollPeriod(
        period_start=payload.period_start,
        period_end=payload.period_end,
        title=payload.title or f"{payload.period_start} – {payload.period_end}",
        overtime_multiplier_percent=payload.overtime_multiplier_percent,
    )
    session.add(period)
    session.flush()
    add_audit(
        session,
        "payroll_period",
        period.id,
        "created",
        {"period_start": period.period_start, "period_end": period.period_end},
    )
    session.commit()
    session.refresh(period)
    return _detail(session, period)


@router.get("/payroll-periods", response_model=list[PeriodRead])
def list_periods(
    session: Session = Depends(get_session),
    state: str | None = Query(default=None, pattern="^(draft|calculated|finalized|closed)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(PayrollPeriod).where(PayrollPeriod.status == RecordStatus.ACTIVE)
    if state:
        query = query.where(PayrollPeriod.state == state)
    return session.scalars(
        query.order_by(PayrollPeriod.period_start.desc()).limit(limit).offset(offset)
    ).all()


@router.get("/payroll-periods/{period_id}", response_model=PeriodDetail)
def read_period(period_id: str, session: Session = Depends(get_session)):
    return _detail(session, get_period(session, period_id))


@router.post("/payroll-periods/{period_id}/calculate", response_model=PeriodDetail)
def calculate_period(
    period_id: str,
    payload: CalculateRequest = Body(default_factory=CalculateRequest),
    session: Session = Depends(get_session),
):
    period = get_period(session, period_id)
    if period.state not in ("draft", "calculated"):
        raise ApiError(
            "period_locked",
            "Kesinleşmiş veya kapanmış dönem yeniden hesaplanamaz; düzeltme hareketi kullanın.",
            409,
        )
    computed = compute_period(session, period, payload)
    existing = {
        entry.employee_id: entry
        for entry in session.scalars(
            select(PayrollEntry).where(PayrollEntry.payroll_period_id == period.id)
        )
    }
    seen: set[str] = set()
    for item in computed:
        employee_id = item["employee_id"]
        seen.add(employee_id)
        entry = existing.get(employee_id)
        if entry is None:
            entry = PayrollEntry(payroll_period_id=period.id, **item)
            session.add(entry)
        else:
            for key, value in item.items():
                setattr(entry, key, value)
            entry.status = RecordStatus.ACTIVE
    for employee_id, entry in existing.items():
        if employee_id not in seen and entry.status == RecordStatus.ACTIVE:
            entry.status = RecordStatus.CANCELLED
    session.flush()
    refresh_entry_balances(session, period)
    period.state = "calculated"
    period.calculated_at = datetime.now(UTC)
    _count, _totals = period_totals(session, period.id)
    add_audit(
        session,
        "payroll_period",
        period.id,
        "calculated",
        {"entries": len(computed), "net_due_kurus": sum(i["net_due_kurus"] for i in computed)},
    )
    session.commit()
    session.refresh(period)
    return _detail(session, period)


@router.get("/payroll-periods/{period_id}/entries", response_model=list[EntryRead])
def list_entries(
    period_id: str,
    session: Session = Depends(get_session),
    employee_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    get_period(session, period_id)
    query = (
        select(PayrollEntry)
        .join(Employee, Employee.id == PayrollEntry.employee_id)
        .where(
            PayrollEntry.payroll_period_id == period_id,
            PayrollEntry.status == RecordStatus.ACTIVE,
        )
    )
    if employee_id:
        query = query.where(PayrollEntry.employee_id == employee_id)
    entries = session.scalars(
        query.order_by(func.lower(Employee.name), PayrollEntry.id).limit(limit).offset(offset)
    ).all()
    return serialize_entries(session, list(entries))


@router.post("/payroll-periods/{period_id}/finalize", response_model=PeriodDetail)
def finalize_period(
    period_id: str,
    payload: FinalizeRequest = Body(default_factory=FinalizeRequest),
    session: Session = Depends(get_session),
):
    period = get_period(session, period_id)
    if period.state != "calculated":
        raise ApiError(
            "period_not_calculated",
            "Yalnız hesaplanmış dönem kesinleştirilebilir.",
            409,
            {"state": period.state},
        )
    # attendance_enforcement_start_date sonrasında zorunlu iş günü puantajsız personel varsa engellenir.
    assert_attendance_complete(session, period)
    entries = list(
        session.scalars(
            select(PayrollEntry).where(
                PayrollEntry.payroll_period_id == period.id,
                PayrollEntry.status == RecordStatus.ACTIVE,
            )
        )
    )
    # Hesaptan sonra puantaj/girdi değiştiyse eski toplamları kesinleştirmeyiz.
    fresh = compute_period(
        session,
        period,
        CalculateRequest(
            auto_advance_deduction=False,
            advance_deductions={e.employee_id: e.advance_deduction_kurus for e in entries},
        ),
    )
    if {(i["employee_id"], signature(i)) for i in fresh} != {
        (e.employee_id, signature(e)) for e in entries
    }:
        raise ApiError(
            "payroll_stale",
            "Hesaplamadan sonra puantaj veya girdiler değişti; önce yeniden hesaplayın.",
            409,
        )
    try:
        backup = backup_manager.create("pre_finalize")
    except BackupError as exc:
        raise ApiError(
            "backup_failed", f"Kesinleştirmeden önce yedek alınamadı: {exc.message}", 409
        ) from exc
    period.state = "finalized"
    period.finalized_at = datetime.now(UTC)
    session.flush()
    post_finalize_ledger(session, period, entries, payload.payment_due_date)
    refresh_entry_balances(session, period)
    add_audit(
        session,
        "payroll_period",
        period.id,
        "finalized",
        {"backup_id": backup.backup_id, "entries": len(entries)},
    )
    session.commit()
    session.refresh(period)
    return _detail(session, period)


@router.post("/payroll-periods/{period_id}/close", response_model=PeriodDetail)
def close_period(
    period_id: str,
    payload: CloseRequest = Body(default_factory=CloseRequest),
    session: Session = Depends(get_session),
):
    period = get_period(session, period_id)
    if period.state != "finalized":
        raise ApiError(
            "period_not_finalized",
            "Yalnız kesinleşmiş dönem kapatılabilir.",
            409,
            {"state": period.state},
        )
    _count, totals = period_totals(session, period.id)
    if totals["remaining_kurus"] > 0 and not payload.allow_unpaid:
        raise ApiError(
            "period_has_unpaid",
            "Dönemde ödenmemiş maaş var; ödeyin veya allow_unpaid ile kapatın.",
            409,
            {"remaining_kurus": totals["remaining_kurus"]},
        )
    period.state = "closed"
    period.closed_at = datetime.now(UTC)
    add_audit(
        session,
        "payroll_period",
        period.id,
        "closed",
        {"remaining_kurus": totals["remaining_kurus"]},
    )
    session.commit()
    session.refresh(period)
    return _detail(session, period)


# --- Dışa aktarma (ekranla aynı hesap fonksiyonu) ---------------------------------------------------

ENTRY_COLUMNS = [
    Column("employee_name", "Personel"),
    Column("wage_type", "Ücret türü"),
    Column("base_rate_kurus", "Ücret", "money"),
    Column("normal_hours", "Normal saat", "number"),
    Column("overtime_hours", "Fazla mesai saat", "number"),
    Column("worked_days", "Gün", "number"),
    Column("base_earning_kurus", "Taban kazanç", "money"),
    Column("overtime_earning_kurus", "Fazla mesai", "money"),
    Column("bonus_kurus", "Prim", "money"),
    Column("additional_earning_kurus", "Ek kazanç", "money"),
    Column("deduction_kurus", "Kesinti", "money"),
    Column("advance_deduction_kurus", "Avans mahsubu", "money"),
    Column("gross_earning_kurus", "Brüt kazanç", "money"),
    Column("net_due_kurus", "Net ödenecek", "money"),
    Column("paid_kurus", "Ödenen", "money"),
    Column("remaining_kurus", "Kalan", "money"),
]
TOTAL_KEYS = [c.key for c in ENTRY_COLUMNS if c.kind == "money" and c.key != "base_rate_kurus"]


def payroll_period_table(session: Session, period: PayrollPeriod) -> ReportTable:
    entries = session.scalars(
        select(PayrollEntry)
        .join(Employee, Employee.id == PayrollEntry.employee_id)
        .where(
            PayrollEntry.payroll_period_id == period.id,
            PayrollEntry.status == RecordStatus.ACTIVE,
        )
        .order_by(func.lower(Employee.name), PayrollEntry.id)
    ).all()
    rows = []
    for read in serialize_entries(session, list(entries)):
        row = read.model_dump(mode="json")
        row.pop("calculation_detail", None)
        rows.append(row)
    _count, totals = period_totals(session, period.id)
    return ReportTable(
        name="payroll-period-summary",
        title=f"Maaş Dönemi: {period.title} ({period.state})",
        columns=ENTRY_COLUMNS,
        rows=rows,
        totals={key: totals[key] for key in TOTAL_KEYS},
        filters={"payroll_period_id": period.id},
    )


@router.get("/payroll-periods/{period_id}/export.xlsx")
def export_period_xlsx(period_id: str, session: Session = Depends(get_session)):
    period = get_period(session, period_id)
    return xlsx_response(payroll_period_table(session, period), f"maas-donemi-{period.period_start}.xlsx")


@router.get("/payroll-periods/{period_id}/export.pdf")
def export_period_pdf(period_id: str, session: Session = Depends(get_session)):
    period = get_period(session, period_id)
    return pdf_response(payroll_period_table(session, period), f"maas-donemi-{period.period_start}.pdf")

"""Devam yönetimi: ayarlar, resmî tatiller, haftalık çalışma planı, zorunlu iş günü ve maaş vadesi.

Zorunlu iş günü = personelin işe giriş/çıkış aralığında, haftalık planda çalışma günü olan ve resmî tatil
olmayan gün. `attendance_enforcement_start_date` öncesinde eski davranış korunur (kaydı olmayan gün
engel değildir); bu tarihten itibaren zorunlu günü puantajsız personelin maaş dönemi kesinleştirilemez.
Tarih kaynağı her yerde `clock.business_today` veya açık parametredir; sistem saati gizlice okunmaz.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_sidecar_token
from .database import get_session
from .models import (
    AppSetting,
    Employee,
    LeaveRequest,
    PayrollEntry,
    PayrollPeriod,
    PublicHoliday,
    RecordStatus,
    WeeklyWorkPlan,
    WorkLog,
    WorkLogDuplicateReport,
)
from .schemas import OrmModel

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])

DEFAULT_WORKDAYS = "1111110"  # Pazartesi–Cumartesi çalışma, Pazar haftalık izin
WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WORKED_STATUSES = frozenset({"worked", "half_day", "overtime"})
KEY_ENFORCEMENT = "attendance_enforcement_start_date"
KEY_SALARY_DAY = "default_salary_day"
KEY_NEGATIVE_LEAVE = "allow_negative_leave_balance"
MAX_LISTED_DATES = 62


# --- Ayarlar ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AttendanceSettings:
    enforcement_start: date | None = None
    default_salary_day: int | None = None
    allow_negative_leave_balance: bool = False


def load_attendance_settings(session: Session) -> AttendanceSettings:
    stored = {
        key: value
        for key, value in session.execute(select(AppSetting.key, AppSetting.value)).all()
        if key in (KEY_ENFORCEMENT, KEY_SALARY_DAY, KEY_NEGATIVE_LEAVE)
    }
    return AttendanceSettings(
        enforcement_start=date.fromisoformat(stored[KEY_ENFORCEMENT])
        if stored.get(KEY_ENFORCEMENT)
        else None,
        default_salary_day=int(stored[KEY_SALARY_DAY]) if stored.get(KEY_SALARY_DAY) else None,
        allow_negative_leave_balance=stored.get(KEY_NEGATIVE_LEAVE) == "true",
    )


class AttendanceSettingsRead(BaseModel):
    attendance_enforcement_start_date: date | None
    default_salary_day: int | None
    allow_negative_leave_balance: bool


class AttendanceSettingsUpdate(BaseModel):
    attendance_enforcement_start_date: date | None = None
    default_salary_day: int | None = Field(default=None, ge=1, le=31)
    allow_negative_leave_balance: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> AttendanceSettingsUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir ayar gönderilmelidir.")
        if (
            "allow_negative_leave_balance" in self.model_fields_set
            and self.allow_negative_leave_balance is None
        ):
            raise ValueError("allow_negative_leave_balance boş bırakılamaz.")
        return self


def _settings_read(settings: AttendanceSettings) -> AttendanceSettingsRead:
    return AttendanceSettingsRead(
        attendance_enforcement_start_date=settings.enforcement_start,
        default_salary_day=settings.default_salary_day,
        allow_negative_leave_balance=settings.allow_negative_leave_balance,
    )


@router.get("/settings/attendance", response_model=AttendanceSettingsRead)
def get_attendance_settings(session: Session = Depends(get_session)):
    return _settings_read(load_attendance_settings(session))


@router.put("/settings/attendance", response_model=AttendanceSettingsRead)
def update_attendance_settings(
    payload: AttendanceSettingsUpdate, session: Session = Depends(get_session)
):
    before = _settings_read(load_attendance_settings(session)).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    mapping = {
        "attendance_enforcement_start_date": KEY_ENFORCEMENT,
        "default_salary_day": KEY_SALARY_DAY,
        "allow_negative_leave_balance": KEY_NEGATIVE_LEAVE,
    }
    for field, key in mapping.items():
        if field not in changes:
            continue
        value = changes[field]
        row = session.get(AppSetting, key)
        if value is None:
            if row is not None:
                session.delete(row)
            continue
        text_value = ("true" if value else "false") if isinstance(value, bool) else str(value)
        if row is None:
            session.add(AppSetting(key=key, value=text_value))
        else:
            row.value = text_value
    session.flush()
    after = _settings_read(load_attendance_settings(session)).model_dump(mode="json")
    add_audit(
        session, "app_settings", "attendance", "updated", {"before": before, "after": after}
    )
    session.commit()
    return _settings_read(load_attendance_settings(session))


# --- Resmî tatiller -----------------------------------------------------------------------------


class HolidayCreate(BaseModel):
    holiday_date: date
    name: str = Field(min_length=2, max_length=180)
    is_half_day: bool = False


class HolidayRead(OrmModel):
    id: str
    holiday_date: date
    name: str
    is_half_day: bool
    status: RecordStatus


@router.post("/holidays", response_model=HolidayRead, status_code=201)
def create_holiday(payload: HolidayCreate, session: Session = Depends(get_session)):
    holiday = PublicHoliday(**payload.model_dump())
    session.add(holiday)
    try:
        session.flush()
        add_audit(session, "public_holiday", holiday.id, "created", {"date": holiday.holiday_date})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            "duplicate_holiday", "Bu tarih için resmî tatil zaten tanımlı.", 409
        ) from exc
    session.refresh(holiday)
    return holiday


@router.get("/holidays", response_model=list[HolidayRead])
def list_holidays(
    session: Session = Depends(get_session),
    year: int | None = Query(default=None, ge=2000, le=2100),
    date_from: date | None = None,
    date_to: date | None = None,
    include_cancelled: bool = False,
):
    query = select(PublicHoliday)
    if not include_cancelled:
        query = query.where(PublicHoliday.status == RecordStatus.ACTIVE)
    if year:
        query = query.where(
            PublicHoliday.holiday_date >= date(year, 1, 1),
            PublicHoliday.holiday_date <= date(year, 12, 31),
        )
    if date_from:
        query = query.where(PublicHoliday.holiday_date >= date_from)
    if date_to:
        query = query.where(PublicHoliday.holiday_date <= date_to)
    return session.scalars(query.order_by(PublicHoliday.holiday_date, PublicHoliday.id)).all()


@router.post("/holidays/{holiday_id}/cancel", response_model=HolidayRead)
def cancel_holiday(holiday_id: str, session: Session = Depends(get_session)):
    holiday = session.get(PublicHoliday, holiday_id)
    if holiday is None:
        raise ApiError("not_found", "Resmî tatil bulunamadı.", 404)
    if holiday.status != RecordStatus.ACTIVE:
        raise ApiError("holiday_cancelled", "Resmî tatil zaten iptal edilmiş.", 409)
    holiday.status = RecordStatus.CANCELLED
    add_audit(session, "public_holiday", holiday.id, "cancelled")
    session.commit()
    session.refresh(holiday)
    return holiday


def holiday_dates(session: Session, start: date, end: date) -> set[date]:
    return set(
        session.scalars(
            select(PublicHoliday.holiday_date).where(
                PublicHoliday.status == RecordStatus.ACTIVE,
                PublicHoliday.holiday_date >= start,
                PublicHoliday.holiday_date <= end,
            )
        )
    )


# --- Haftalık çalışma planı ---------------------------------------------------------------------


class PlanCreate(BaseModel):
    employee_id: str | None = None  # boşsa şirket planı
    effective_from: date
    workdays: list[int] = Field(min_length=0, max_length=7)  # ISO hafta günü: 1=Pazartesi … 7=Pazar
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_days(self) -> PlanCreate:
        if any(day < 1 or day > 7 for day in self.workdays) or len(set(self.workdays)) != len(
            self.workdays
        ):
            raise ValueError("workdays 1–7 arasında benzersiz hafta günlerinden oluşmalıdır.")
        return self


class PlanRead(OrmModel):
    id: str
    employee_id: str | None
    effective_from: date
    effective_to: date | None
    workdays: str
    note: str | None
    status: RecordStatus
    workday_numbers: list[int] = Field(default_factory=list)


def _plan_read(plan: WeeklyWorkPlan) -> PlanRead:
    read = PlanRead.model_validate(plan)
    read.workday_numbers = [i + 1 for i, flag in enumerate(plan.workdays) if flag == "1"]
    return read


@router.post("/weekly-work-plans", response_model=PlanRead, status_code=201)
def create_plan(payload: PlanCreate, session: Session = Depends(get_session)):
    if payload.employee_id and session.get(Employee, payload.employee_id) is None:
        raise ApiError("not_found", "Personel bulunamadı.", 404)
    previous = session.scalars(
        select(WeeklyWorkPlan)
        .where(
            WeeklyWorkPlan.employee_id == payload.employee_id
            if payload.employee_id
            else WeeklyWorkPlan.employee_id.is_(None),
            WeeklyWorkPlan.status == RecordStatus.ACTIVE,
        )
        .order_by(WeeklyWorkPlan.effective_from.desc())
    ).first()
    if previous is not None and previous.effective_from >= payload.effective_from:
        raise ApiError(
            "plan_order",
            "Yeni planın başlangıcı mevcut planın başlangıcından sonra olmalıdır.",
            409,
            {"previous_effective_from": previous.effective_from},
        )
    if previous is not None and (
        previous.effective_to is None or previous.effective_to >= payload.effective_from
    ):
        previous.effective_to = payload.effective_from - timedelta(days=1)
    plan = WeeklyWorkPlan(
        employee_id=payload.employee_id,
        effective_from=payload.effective_from,
        workdays="".join("1" if i + 1 in payload.workdays else "0" for i in range(7)),
        note=payload.note,
    )
    session.add(plan)
    session.flush()
    add_audit(
        session, "weekly_work_plan", plan.id, "created",
        {"employee_id": payload.employee_id, "workdays": plan.workdays},
    )
    session.commit()
    session.refresh(plan)
    return _plan_read(plan)


@router.get("/weekly-work-plans", response_model=list[PlanRead])
def list_plans(
    session: Session = Depends(get_session),
    employee_id: str | None = None,
    company_only: bool = False,
):
    query = select(WeeklyWorkPlan).where(WeeklyWorkPlan.status == RecordStatus.ACTIVE)
    if company_only:
        query = query.where(WeeklyWorkPlan.employee_id.is_(None))
    elif employee_id:
        query = query.where(WeeklyWorkPlan.employee_id == employee_id)
    plans = session.scalars(
        query.order_by(WeeklyWorkPlan.employee_id, WeeklyWorkPlan.effective_from)
    ).all()
    return [_plan_read(plan) for plan in plans]


class PlanBook:
    """Personel planı varsa o, yoksa şirket planı, yoksa Pazartesi–Cumartesi varsayılanı."""

    def __init__(self, session: Session):
        self.plans: dict[str | None, list[WeeklyWorkPlan]] = {}
        for plan in session.scalars(
            select(WeeklyWorkPlan)
            .where(WeeklyWorkPlan.status == RecordStatus.ACTIVE)
            .order_by(WeeklyWorkPlan.effective_from)
        ):
            self.plans.setdefault(plan.employee_id, []).append(plan)

    def _at(self, scope: str | None, day: date) -> str | None:
        found = None
        for plan in self.plans.get(scope, []):
            if plan.effective_from <= day and (plan.effective_to is None or plan.effective_to >= day):
                found = plan.workdays
        return found

    def workdays(self, employee_id: str, day: date) -> str:
        return self._at(employee_id, day) or self._at(None, day) or DEFAULT_WORKDAYS

    def is_working_day(self, employee_id: str, day: date) -> bool:
        return self.workdays(employee_id, day)[day.isoweekday() - 1] == "1"


# --- Zorunlu iş günü ----------------------------------------------------------------------------


def day_classification(
    employee: Employee, day: date, plans: PlanBook, holidays: set[date]
) -> str:
    """workday | weekly_rest | public_holiday | outside_employment."""
    if employee.employment_start_date and day < employee.employment_start_date:
        return "outside_employment"
    if employee.employment_end_date and day > employee.employment_end_date:
        return "outside_employment"
    if day in holidays:
        return "public_holiday"
    if not plans.is_working_day(employee.id, day):
        return "weekly_rest"
    return "workday"


def required_days(
    employee: Employee, start: date, end: date, plans: PlanBook, holidays: set[date]
) -> list[date]:
    days = []
    cursor = start
    while cursor <= end:
        if day_classification(employee, cursor, plans, holidays) == "workday":
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _active_logs(
    session: Session, employee_ids: list[str] | None, start: date, end: date
) -> dict[str, dict[date, WorkLog]]:
    query = select(WorkLog).where(
        WorkLog.status == RecordStatus.ACTIVE, WorkLog.work_date >= start, WorkLog.work_date <= end
    )
    if employee_ids is not None:
        query = query.where(WorkLog.employee_id.in_(employee_ids or [""]))
    logs: dict[str, dict[date, WorkLog]] = {}
    for log in session.scalars(query):
        logs.setdefault(log.employee_id, {})[log.work_date] = log
    return logs


def missing_enforced_days(
    session: Session, employees: list[Employee], start: date, end: date
) -> dict[str, list[date]]:
    """Zorunlu olup puantajı olmayan günler (yalnız enforcement başlangıcından itibaren)."""
    settings = load_attendance_settings(session)
    if settings.enforcement_start is None or end < settings.enforcement_start or not employees:
        return {}
    lo = max(start, settings.enforcement_start)
    plans = PlanBook(session)
    holidays = holiday_dates(session, lo, end)
    logs = _active_logs(session, [e.id for e in employees], lo, end)
    missing: dict[str, list[date]] = {}
    for employee in employees:
        have = logs.get(employee.id, {})
        gaps = [d for d in required_days(employee, lo, end, plans, holidays) if d not in have]
        if gaps:
            missing[employee.id] = gaps
    return missing


def assert_attendance_complete(session: Session, period: PayrollPeriod) -> None:
    """Kesinleştirmeyi engeller: enforcement sonrası zorunlu günü puantajsız personel varsa 409."""
    entries = session.scalars(
        select(PayrollEntry.employee_id).where(
            PayrollEntry.payroll_period_id == period.id,
            PayrollEntry.status == RecordStatus.ACTIVE,
        )
    ).all()
    employees = list(
        session.scalars(select(Employee).where(Employee.id.in_(list(entries) or [""])))
    )
    missing = missing_enforced_days(session, employees, period.period_start, period.period_end)
    if not missing:
        return
    names = {e.id: e.name for e in employees}
    raise ApiError(
        "attendance_incomplete",
        "Zorunlu çalışma günlerinde puantajı eksik personel var; kesinleştirmeden önce tamamlayın.",
        409,
        {
            "enforcement_start_date": load_attendance_settings(session).enforcement_start,
            "employees": [
                {
                    "employee_id": employee_id,
                    "employee_name": names[employee_id],
                    "missing_count": len(days),
                    "missing_dates": days[:MAX_LISTED_DATES],
                }
                for employee_id, days in sorted(missing.items(), key=lambda kv: names[kv[0]])
            ],
        },
    )


# --- Kontrol ve takvim uçları -------------------------------------------------------------------


def _check_range(
    session: Session, start: date, end: date, employee_id: str | None, period_id: str | None
) -> tuple[date, date, list[Employee]]:
    if period_id:
        period = session.get(PayrollPeriod, period_id)
        if period is None or period.status != RecordStatus.ACTIVE:
            raise ApiError("not_found", "Maaş dönemi bulunamadı.", 404)
        start, end = period.period_start, period.period_end
    if end < start:
        raise ApiError("invalid_range", "Başlangıç tarihi bitiş tarihinden sonra olamaz.", 422)
    if (end - start).days > 366:
        raise ApiError("range_too_large", "Aralık en fazla 367 gün olabilir.", 422)
    query = select(Employee).where(Employee.status != RecordStatus.CANCELLED)
    if employee_id:
        query = query.where(Employee.id == employee_id)
    else:
        query = query.where(
            Employee.status == RecordStatus.ACTIVE,
            (Employee.employment_start_date.is_(None) | (Employee.employment_start_date <= end)),
            (Employee.employment_end_date.is_(None) | (Employee.employment_end_date >= start)),
        )
    employees = list(session.scalars(query.order_by(Employee.name, Employee.id)))
    if employee_id and not employees:
        raise ApiError("not_found", "Personel bulunamadı.", 404)
    return start, end, employees


@router.get("/attendance/check")
def attendance_check(
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: str | None = None,
    payroll_period_id: str | None = None,
    include_clean: bool = False,
    session: Session = Depends(get_session),
):
    """Puantaj eksikliği ve uyumsuzluk raporu. `enforced` eksikler maaş kesinleştirmeyi engeller."""
    if payroll_period_id is None and (date_from is None or date_to is None):
        raise ApiError(
            "range_required", "date_from ve date_to (veya payroll_period_id) gereklidir.", 422
        )
    start, end, employees = _check_range(
        session, date_from or date.min, date_to or date.min, employee_id, payroll_period_id
    )
    settings = load_attendance_settings(session)
    plans = PlanBook(session)
    holidays = holiday_dates(session, start, end)
    ids = [e.id for e in employees]
    logs = _active_logs(session, ids, start, end)
    approved = session.scalars(
        select(LeaveRequest).where(
            LeaveRequest.employee_id.in_(ids or [""]),
            LeaveRequest.request_state == "approved",
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start,
        )
    ).all()
    leave_logs = {
        (log.leave_request_id, log.work_date)
        for by_day in logs.values()
        for log in by_day.values()
        if log.leave_request_id
    }
    rows = []
    totals = {"missing_required_day": 0, "enforced_missing_day": 0, "inconsistency": 0}
    for employee in employees:
        have = logs.get(employee.id, {})
        issues: list[dict] = []
        required = required_days(employee, start, end, plans, holidays)
        for day in required:
            if day in have:
                continue
            enforced = settings.enforcement_start is not None and day >= settings.enforcement_start
            issues.append({"code": "missing_required_day", "date": day, "enforced": enforced})
            totals["missing_required_day"] += 1
            totals["enforced_missing_day"] += int(enforced)
        for day, log in sorted(have.items()):
            kind = day_classification(employee, day, plans, holidays)
            if kind == "outside_employment":
                code = "log_outside_employment"
            elif kind == "weekly_rest" and log.work_status in WORKED_STATUSES:
                code = "worked_on_weekly_rest"
            elif kind == "public_holiday" and log.work_status in WORKED_STATUSES:
                code = "worked_on_public_holiday"
            else:
                continue
            issues.append({"code": code, "date": day, "work_log_id": log.id, "enforced": False})
            totals["inconsistency"] += 1
        for request in approved:
            if request.employee_id != employee.id:
                continue
            cursor = max(request.start_date, start)
            while cursor <= min(request.end_date, end):
                if (
                    day_classification(employee, cursor, plans, holidays) == "workday"
                    and (request.id, cursor) not in leave_logs
                ):
                    issues.append(
                        {
                            "code": "approved_leave_without_log",
                            "date": cursor,
                            "leave_request_id": request.id,
                            "enforced": False,
                        }
                    )
                    totals["inconsistency"] += 1
                cursor += timedelta(days=1)
        if issues or include_clean:
            issues.sort(key=lambda item: (item["date"], item["code"]))
            rows.append(
                {
                    "employee_id": employee.id,
                    "employee_name": employee.name,
                    "required_day_count": len(required),
                    "logged_day_count": len(have),
                    "issues": issues,
                }
            )
    return {
        "date_from": start,
        "date_to": end,
        "enforcement_start_date": settings.enforcement_start,
        "employees_checked": len(employees),
        "totals": totals,
        "employees": rows,
    }


@router.get("/employees/{employee_id}/work-calendar")
def work_calendar(
    employee_id: str,
    date_from: date,
    date_to: date,
    session: Session = Depends(get_session),
):
    start, end, employees = _check_range(session, date_from, date_to, employee_id, None)
    employee = employees[0]
    plans = PlanBook(session)
    holidays = holiday_dates(session, start, end)
    logs = _active_logs(session, [employee.id], start, end).get(employee.id, {})
    days = []
    cursor = start
    while cursor <= end:
        kind = day_classification(employee, cursor, plans, holidays)
        log = logs.get(cursor)
        days.append(
            {
                "date": cursor,
                "weekday": WEEKDAY_NAMES[cursor.weekday()],
                "day_type": kind,
                "required": kind == "workday",
                "work_log_id": log.id if log else None,
                "work_status": log.work_status if log else None,
                "leave_request_id": log.leave_request_id if log else None,
            }
        )
        cursor += timedelta(days=1)
    return {"employee_id": employee.id, "date_from": start, "date_to": end, "days": days}


@router.get("/attendance/duplicate-reports")
def duplicate_reports(
    session: Session = Depends(get_session),
    employee_id: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Migration sırasında bulunan mükerrer puantajlar (hangisi korundu, hangisi iptal edildi)."""
    query = select(WorkLogDuplicateReport)
    if employee_id:
        query = query.where(WorkLogDuplicateReport.employee_id == employee_id)
    rows = session.scalars(
        query.order_by(WorkLogDuplicateReport.work_date, WorkLogDuplicateReport.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [
        {
            "id": r.id,
            "employee_id": r.employee_id,
            "work_date": r.work_date,
            "kept_work_log_id": r.kept_work_log_id,
            "cancelled_work_log_id": r.cancelled_work_log_id,
            "kept_amount_kurus": r.kept_amount_kurus,
            "cancelled_amount_kurus": r.cancelled_amount_kurus,
            "kept_work_status": r.kept_work_status,
            "cancelled_work_status": r.cancelled_work_status,
            "in_locked_period": r.in_locked_period,
            "resolution": r.resolution,
            "detail": r.detail,
        }
        for r in rows
    ]


# --- Maaş vadesi --------------------------------------------------------------------------------


def derive_due_date(period_end: date, salary_day: int) -> date:
    """Dönem bitişinden sonraki ilk maaş günü (ay sonunu aşan gün ay sonuna indirilir)."""

    def clamp(year: int, month: int) -> date:
        return date(year, month, min(salary_day, calendar.monthrange(year, month)[1]))

    candidate = clamp(period_end.year, period_end.month)
    if candidate > period_end:
        return candidate
    year, month = (period_end.year + 1, 1) if period_end.month == 12 else (
        period_end.year,
        period_end.month + 1,
    )
    return clamp(year, month)


def salary_due_date(
    employee: Employee | None, period_end: date, settings: AttendanceSettings
) -> date | None:
    """İşletme maaş vadesi: kesimi izleyen ayın 10'u."""
    return derive_due_date(period_end, 10)


@router.get("/payroll-periods/{period_id}/salary-due-dates")
def period_salary_due_dates(period_id: str, session: Session = Depends(get_session)):
    period = session.get(PayrollPeriod, period_id)
    if period is None or period.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "Maaş dönemi bulunamadı.", 404)
    settings = load_attendance_settings(session)
    employees = session.scalars(
        select(Employee)
        .join(PayrollEntry, PayrollEntry.employee_id == Employee.id)
        .where(
            PayrollEntry.payroll_period_id == period.id,
            PayrollEntry.status == RecordStatus.ACTIVE,
        )
        .order_by(Employee.name, Employee.id)
    ).all()
    return {
        "payroll_period_id": period.id,
        "period_end": period.period_end,
        "default_salary_day": 10,
        "employees": [
            {
                "employee_id": e.id,
                "employee_name": e.name,
                "salary_day": 10,
                "source": "company_fixed",
                "due_date": salary_due_date(e, period.period_end, settings) or period.period_end,
            }
            for e in employees
        ],
    }

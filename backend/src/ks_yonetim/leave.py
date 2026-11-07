"""İzin türleri, izin hak defteri ve izin talepleri.

Hak defteri saat cinsinden işaretlidir (1 gün = `standard_day_hours`): `grant`/`accrual` artırır,
`use` düşer, `adjustment` işaretlidir, `reversal` bir kaydı zıt yönde geri alır. Kayıtlar silinmez.
Bakiye, geçerlilik dönemine göre FIFO tüketimle hesaplanır (önce süresi dolacak hak kullanılır).

Onaylanan izin talebi, haftalık plan ve resmî tatiller dışındaki her gün için puantaj kaydı üretir
(`work_logs.leave_request_id`); kesinleşmiş/kapanmış maaş dönemine denk gelen günlerde engellenir.
Yarım gün ve saatlik izin tek gündür; günün kalan saatleri çalışıldı varsayılır.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import clock
from .api import ApiError, add_audit, require_sidecar_token
from .attendance import (
    PlanBook,
    day_classification,
    holiday_dates,
    load_attendance_settings,
)
from .database import get_session
from .employees import get_employee
from .labor_cost import PAID_STATUSES, load_settings, work_log_amount
from .locks import assert_dates_unlocked, assert_range_unlocked
from .models import (
    Employee,
    LeaveLedgerEntry,
    LeaveRequest,
    LeaveType,
    RecordStatus,
    WorkLog,
)
from .schemas import OrmModel
from .wages import load_rate_book

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])

HOUR = Decimal("0.01")
DEFAULT_LEAVE_TYPES = (
    ("annual", "Yıllık izin", "annual_leave", True),
    ("sick", "Raporlu", "sick_leave", False),
    ("other_paid", "Diğer ücretli izin", "paid_leave", False),
    ("unpaid", "Ücretsiz izin", "unpaid_leave", False),
    ("excused", "Mazeret izni", "excused_leave", False),
)
POSITIVE_TYPES = ("grant", "accrual")


def q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(HOUR)


# --- İzin türleri -------------------------------------------------------------------------------


def ensure_default_leave_types(session: Session) -> None:
    existing = set(session.scalars(select(LeaveType.code)))
    for code, name, work_status, deducts in DEFAULT_LEAVE_TYPES:
        if code not in existing:
            session.add(
                LeaveType(
                    code=code, name=name, work_status=work_status, deducts_entitlement=deducts,
                    is_system=True,
                )
            )
    session.flush()


class LeaveTypeCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern="^[a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=120)
    work_status: Literal["annual_leave", "sick_leave", "excused_leave", "paid_leave", "unpaid_leave"]
    deducts_entitlement: bool = False


class LeaveTypeRead(OrmModel):
    id: str
    code: str
    name: str
    work_status: str
    deducts_entitlement: bool
    is_system: bool
    status: RecordStatus


@router.get("/leave-types", response_model=list[LeaveTypeRead])
def list_leave_types(include_archived: bool = False, session: Session = Depends(get_session)):
    ensure_default_leave_types(session)
    session.commit()
    query = select(LeaveType)
    if not include_archived:
        query = query.where(LeaveType.status == RecordStatus.ACTIVE)
    return session.scalars(query.order_by(LeaveType.is_system.desc(), LeaveType.code)).all()


@router.post("/leave-types", response_model=LeaveTypeRead, status_code=201)
def create_leave_type(payload: LeaveTypeCreate, session: Session = Depends(get_session)):
    ensure_default_leave_types(session)
    leave_type = LeaveType(**payload.model_dump())
    session.add(leave_type)
    try:
        session.flush()
        add_audit(session, "leave_type", leave_type.id, "created", {"code": leave_type.code})
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("duplicate_leave_type", "Bu izin türü kodu zaten kayıtlı.", 409) from exc
    session.refresh(leave_type)
    return leave_type


@router.post("/leave-types/{leave_type_id}/archive", response_model=LeaveTypeRead)
def archive_leave_type(leave_type_id: str, session: Session = Depends(get_session)):
    leave_type = session.get(LeaveType, leave_type_id)
    if leave_type is None:
        raise ApiError("not_found", "İzin türü bulunamadı.", 404)
    if leave_type.is_system:
        raise ApiError("system_leave_type", "Sistem izin türü arşivlenemez.", 409)
    leave_type.status = RecordStatus.ARCHIVED
    add_audit(session, "leave_type", leave_type.id, "archived")
    session.commit()
    session.refresh(leave_type)
    return leave_type


def resolve_leave_type(
    session: Session, leave_type_id: str | None, leave_type_code: str | None, *, default: str | None
) -> LeaveType:
    ensure_default_leave_types(session)
    code = leave_type_code or (default if leave_type_id is None else None)
    query = select(LeaveType)
    query = query.where(LeaveType.id == leave_type_id) if leave_type_id else query.where(
        LeaveType.code == code
    )
    leave_type = session.scalars(query).first()
    if leave_type is None:
        raise ApiError("not_found", "İzin türü bulunamadı.", 404)
    if leave_type.status != RecordStatus.ACTIVE:
        raise ApiError("leave_type_archived", "İzin türü arşivlenmiş.", 409)
    return leave_type


# --- Hak defteri hesapları ----------------------------------------------------------------------


@dataclass
class Pool:
    entry: LeaveLedgerEntry
    remaining: Decimal
    valid_from: date
    valid_to: date | None


def effective_entries(
    session: Session, employee_id: str, leave_type_id: str
) -> list[LeaveLedgerEntry]:
    rows = list(
        session.scalars(
            select(LeaveLedgerEntry).where(
                LeaveLedgerEntry.employee_id == employee_id,
                LeaveLedgerEntry.leave_type_id == leave_type_id,
                LeaveLedgerEntry.status == RecordStatus.ACTIVE,
            )
        )
    )
    voided = {r.reversed_entry_id for r in rows if r.entry_type == "reversal"}
    return [r for r in rows if r.entry_type != "reversal" and r.id not in voided]


def compute_balance(entries: list[LeaveLedgerEntry], as_of: date, day_hours: int) -> dict:
    """FIFO tüketimle bakiye: hak havuzları geçerlilik dönemine göre, kullanım tarih sırasına göre."""
    pools: list[Pool] = []
    drains: list[LeaveLedgerEntry] = []
    granted = used = adjusted = Decimal(0)
    for entry in entries:
        if entry.entry_date > as_of:
            continue
        qty = Decimal(entry.quantity_hours)
        if entry.entry_type in POSITIVE_TYPES or (entry.entry_type == "adjustment" and qty > 0):
            pools.append(
                Pool(entry, qty, entry.valid_from or entry.entry_date, entry.valid_to)
            )
            if entry.entry_type == "adjustment":
                adjusted += qty
            else:
                granted += qty
        else:
            drains.append(entry)
            if entry.entry_type == "adjustment":
                adjusted += qty
            else:
                used += -qty
    pools.sort(key=lambda p: (p.valid_to or date.max, p.valid_from, p.entry.id))
    overdrawn = Decimal(0)
    for drain in sorted(drains, key=lambda e: (e.entry_date, e.id)):
        need = -Decimal(drain.quantity_hours)
        for pool in pools:
            if need <= 0:
                break
            if pool.valid_from > drain.entry_date or (
                pool.valid_to is not None and pool.valid_to < drain.entry_date
            ):
                continue
            take = min(pool.remaining, need)
            pool.remaining -= take
            need -= take
        overdrawn += max(need, Decimal(0))
    available = sum(
        (
            p.remaining
            for p in pools
            if p.valid_from <= as_of and (p.valid_to is None or p.valid_to >= as_of)
        ),
        Decimal(0),
    )
    expired = sum(
        (p.remaining for p in pools if p.valid_to is not None and p.valid_to < as_of), Decimal(0)
    )
    balance = available - overdrawn
    divisor = Decimal(day_hours)
    return {
        "as_of": as_of,
        "granted_hours": q(granted),
        "used_hours": q(used),
        "adjusted_hours": q(adjusted),
        "expired_hours": q(expired),
        "available_hours": q(available),
        "overdrawn_hours": q(overdrawn),
        "balance_hours": q(balance),
        "granted_days": q(granted / divisor),
        "used_days": q(used / divisor),
        "available_days": q(available / divisor),
        "balance_days": q(balance / divisor),
        "standard_day_hours": day_hours,
    }


def balance_for(
    session: Session, employee_id: str, leave_type_id: str, as_of: date
) -> dict:
    return compute_balance(
        effective_entries(session, employee_id, leave_type_id),
        as_of,
        load_settings(session).standard_day_hours,
    )


# --- Hak defteri uçları -------------------------------------------------------------------------


class LedgerCreate(BaseModel):
    leave_type_id: str | None = None
    leave_type_code: str | None = None
    entry_type: Literal["grant", "accrual", "adjustment"]
    quantity_days: Decimal | None = Field(default=None, decimal_places=2)
    quantity_hours: Decimal | None = Field(default=None, decimal_places=2)
    entry_date: date
    valid_from: date | None = None
    valid_to: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def validate_entry(self) -> LedgerCreate:
        if (self.quantity_days is None) == (self.quantity_hours is None):
            raise ValueError("quantity_days veya quantity_hours'tan yalnız biri gönderilmelidir.")
        amount = self.quantity_days if self.quantity_days is not None else self.quantity_hours
        assert amount is not None
        if amount == 0:
            raise ValueError("Miktar sıfır olamaz.")
        if self.entry_type != "adjustment" and amount < 0:
            raise ValueError("Hak/hakediş miktarı pozitif olmalıdır; azaltma için adjustment kullanın.")
        if self.entry_type == "adjustment" and (self.valid_from or self.valid_to):
            raise ValueError("Düzeltme kaydında geçerlilik dönemi girilemez.")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("Geçerlilik bitişi başlangıçtan önce olamaz.")
        return self


class LedgerReverse(BaseModel):
    entry_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class LedgerEntryRead(OrmModel):
    id: str
    employee_id: str
    leave_type_id: str
    entry_type: str
    quantity_hours: Decimal
    entry_date: date
    valid_from: date | None
    valid_to: date | None
    leave_request_id: str | None
    reversed_entry_id: str | None
    source: str
    note: str | None
    idempotency_key: str
    status: RecordStatus
    is_voided: bool = False


def _entry_read(entry: LeaveLedgerEntry, voided: set[str]) -> LedgerEntryRead:
    read = LedgerEntryRead.model_validate(entry)
    read.is_voided = entry.id in voided
    return read


class BalanceRead(BaseModel):
    as_of: date
    granted_hours: Decimal
    used_hours: Decimal
    adjusted_hours: Decimal
    expired_hours: Decimal
    available_hours: Decimal
    overdrawn_hours: Decimal
    balance_hours: Decimal
    granted_days: Decimal
    used_days: Decimal
    available_days: Decimal
    balance_days: Decimal
    standard_day_hours: int


def _insufficient(balance: dict, required: Decimal) -> ApiError:
    return ApiError(
        "insufficient_leave_balance",
        "İzin bakiyesi yetersiz.",
        409,
        {
            "available_hours": str(balance["available_hours"]),
            "required_hours": str(q(required)),
            "overdrawn_hours": str(balance["overdrawn_hours"]),
        },
    )


@router.get("/employees/{employee_id}/leave-ledger")
def read_leave_ledger(
    employee_id: str,
    leave_type_id: str | None = None,
    leave_type_code: str | None = None,
    as_of: date | None = None,
    session: Session = Depends(get_session),
):
    employee = get_employee(session, employee_id)
    leave_type = resolve_leave_type(session, leave_type_id, leave_type_code, default="annual")
    day = as_of or clock.business_today()
    rows = list(
        session.scalars(
            select(LeaveLedgerEntry)
            .where(
                LeaveLedgerEntry.employee_id == employee.id,
                LeaveLedgerEntry.leave_type_id == leave_type.id,
                LeaveLedgerEntry.status == RecordStatus.ACTIVE,
            )
            .order_by(LeaveLedgerEntry.entry_date, LeaveLedgerEntry.created_at, LeaveLedgerEntry.id)
        )
    )
    voided = {r.reversed_entry_id for r in rows if r.entry_type == "reversal"}
    session.commit()
    return {
        "employee_id": employee.id,
        "leave_type": LeaveTypeRead.model_validate(leave_type),
        "balance": BalanceRead(**balance_for(session, employee.id, leave_type.id, day)),
        "entries": [_entry_read(r, voided) for r in rows],
    }


def _hours_from(payload: LedgerCreate, day_hours: int) -> Decimal:
    if payload.quantity_hours is not None:
        return q(payload.quantity_hours)
    assert payload.quantity_days is not None
    return q(payload.quantity_days * day_hours)


@router.post("/employees/{employee_id}/leave-ledger", response_model=LedgerEntryRead, status_code=201)
def create_ledger_entry(
    employee_id: str, payload: LedgerCreate, session: Session = Depends(get_session)
):
    employee = get_employee(session, employee_id, allow_archived=False)
    existing = session.scalar(
        select(LeaveLedgerEntry).where(
            LeaveLedgerEntry.idempotency_key == payload.idempotency_key
        )
    )
    if existing is not None:
        if existing.employee_id != employee.id or existing.entry_type != payload.entry_type:
            raise ApiError("idempotency_conflict", "Bu anahtar başka bir kayıtta kullanılmış.", 409)
        return _entry_read(existing, set())
    leave_type = resolve_leave_type(
        session, payload.leave_type_id, payload.leave_type_code, default="annual"
    )
    if not leave_type.deducts_entitlement:
        raise ApiError(
            "leave_type_without_entitlement",
            "Bu izin türü hak bakiyesi tutmaz.",
            422,
            {"leave_type": leave_type.code},
        )
    settings = load_settings(session)
    hours = _hours_from(payload, settings.standard_day_hours)
    entry = LeaveLedgerEntry(
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        entry_type=payload.entry_type,
        quantity_hours=hours,
        entry_date=payload.entry_date,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
        source="manual",
    )
    session.add(entry)
    session.flush()
    if hours < 0 and not load_attendance_settings(session).allow_negative_leave_balance:
        # Tüm kayıtlar (ileri tarihli kullanımlar dahil) üzerinde açık veren var mı?
        balance = balance_for(session, employee.id, leave_type.id, date.max)
        if balance["overdrawn_hours"] > 0:
            raise _insufficient(balance, -hours)
    add_audit(
        session, "leave_ledger_entry", entry.id, "created",
        {"employee_id": employee.id, "entry_type": entry.entry_type, "quantity_hours": hours},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("idempotency_conflict", "Bu anahtar başka bir kayıtta kullanılmış.", 409) from exc
    session.refresh(entry)
    return _entry_read(entry, set())


@router.post("/leave-ledger/{entry_id}/reverse", response_model=LedgerEntryRead, status_code=201)
def reverse_ledger_entry(
    entry_id: str,
    payload: LedgerReverse | None = None,
    session: Session = Depends(get_session),
):
    payload = payload or LedgerReverse()
    original = session.get(LeaveLedgerEntry, entry_id)
    if original is None or original.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "İzin hak kaydı bulunamadı.", 404)
    if original.entry_type == "reversal":
        raise ApiError("cannot_reverse_reversal", "Ters kayıt tekrar terslenemez.", 409)
    if original.source == "system":
        raise ApiError(
            "system_entry",
            "İzin talebinden üretilen kayıt yalnız izin talebi iptaliyle geri alınır.",
            409,
            {"leave_request_id": original.leave_request_id},
        )
    if session.scalar(
        select(LeaveLedgerEntry.id).where(LeaveLedgerEntry.reversed_entry_id == original.id)
    ):
        raise ApiError("already_reversed", "Bu kayıt zaten terslenmiş.", 409)
    day = payload.entry_date or max(clock.business_today(), original.entry_date)
    if day < original.entry_date:
        raise ApiError(
            "invalid_reversal_date",
            "Ters kayıt tarihi orijinal kayıt tarihinden önce olamaz.",
            422,
            {"original_date": original.entry_date},
        )
    reversal = LeaveLedgerEntry(
        employee_id=original.employee_id,
        leave_type_id=original.leave_type_id,
        entry_type="reversal",
        quantity_hours=-Decimal(original.quantity_hours),
        entry_date=day,
        valid_from=original.valid_from,
        valid_to=original.valid_to,
        reversed_entry_id=original.id,
        source="system",
        note=payload.note or f"Ters kayıt: {original.entry_type}",
        idempotency_key=f"reverse:{original.id}",
    )
    session.add(reversal)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("already_reversed", "Bu kayıt zaten terslenmiş.", 409) from exc
    if not load_attendance_settings(session).allow_negative_leave_balance:
        balance = balance_for(session, original.employee_id, original.leave_type_id, date.max)
        if balance["overdrawn_hours"] > 0:
            raise ApiError(
                "reversal_makes_negative",
                "Bu hakkın terslenmesi izin bakiyesini negatife düşürür.",
                409,
                {"overdrawn_hours": str(balance["overdrawn_hours"])},
            )
    add_audit(session, "leave_ledger_entry", original.id, "reversed", {"reversal_id": reversal.id})
    session.commit()
    session.refresh(reversal)
    return _entry_read(reversal, set())


@router.get("/employees/{employee_id}/leave-entitlement")
def leave_entitlement_suggestion(
    employee_id: str, year: int = Query(ge=2000, le=2100), session: Session = Depends(get_session)
):
    """Kıdeme göre yıllık izin gün önerisi (bilgilendirme; hak ancak defter kaydıyla tanımlanır)."""
    employee = get_employee(session, employee_id)
    start = employee.employment_start_date
    if start is None:
        return {"employee_id": employee.id, "year": year, "completed_years": None,
                "suggested_days": None, "rule": "İşe giriş tarihi girilmemiş."}
    year_end = date(year, 12, 31)
    years = year_end.year - start.year - ((year_end.month, year_end.day) < (start.month, start.day))
    if years < 1:
        days, rule = 0, "Bir yılını doldurmamış personel yıllık izin hakkı kazanmaz."
    elif years < 5:
        days, rule = 14, "1–5 yıl: 14 gün"
    elif years < 15:
        days, rule = 20, "5–15 yıl: 20 gün"
    else:
        days, rule = 26, "15 yıl ve üzeri: 26 gün"
    return {"employee_id": employee.id, "year": year, "completed_years": max(years, 0),
            "suggested_days": days, "rule": rule}


# --- İzin talepleri -----------------------------------------------------------------------------


class LeaveRequestCreate(BaseModel):
    employee_id: str
    leave_type_id: str | None = None
    leave_type_code: str | None = None
    start_date: date
    end_date: date
    day_part: Literal["full", "half_am", "half_pm", "hourly"] = "full"
    hours: Decimal | None = Field(default=None, gt=0, le=24, decimal_places=2)
    reason: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def validate_request(self) -> LeaveRequestCreate:
        if self.leave_type_id is None and self.leave_type_code is None:
            raise ValueError("leave_type_id veya leave_type_code gönderilmelidir.")
        if self.end_date < self.start_date:
            raise ValueError("Bitiş tarihi başlangıçtan önce olamaz.")
        if (self.end_date - self.start_date).days > 365:
            raise ValueError("Bir izin talebi en fazla 366 gün olabilir.")
        if self.day_part != "full" and self.start_date != self.end_date:
            raise ValueError("Yarım gün ve saatlik izin tek günlük olmalıdır.")
        if self.day_part == "hourly" and self.hours is None:
            raise ValueError("Saatlik izinde hours zorunludur.")
        if self.day_part != "hourly" and self.hours is not None:
            raise ValueError("hours yalnız saatlik izinde gönderilir.")
        return self


class LeaveDecision(BaseModel):
    note: str | None = Field(default=None, max_length=255)


class LeaveRequestRead(OrmModel):
    id: str
    employee_id: str
    leave_type_id: str
    start_date: date
    end_date: date
    day_part: str
    hours_per_day: Decimal | None
    total_hours: Decimal | None
    request_state: str
    reason: str | None
    decision_note: str | None
    decided_at: datetime | None
    idempotency_key: str
    status: RecordStatus
    leave_type_code: str | None = None
    work_log_ids: list[str] = Field(default_factory=list)


def _request_read(session: Session, request: LeaveRequest) -> LeaveRequestRead:
    read = LeaveRequestRead.model_validate(request)
    leave_type = session.get(LeaveType, request.leave_type_id)
    read.leave_type_code = leave_type.code if leave_type else None
    read.work_log_ids = list(
        session.scalars(
            select(WorkLog.id)
            .where(
                WorkLog.leave_request_id == request.id, WorkLog.status == RecordStatus.ACTIVE
            )
            .order_by(WorkLog.work_date)
        )
    )
    return read


def _get_request(session: Session, request_id: str) -> LeaveRequest:
    request = session.get(LeaveRequest, request_id)
    if request is None or request.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "İzin talebi bulunamadı.", 404)
    return request


def _hours_per_day(request: LeaveRequest, day_hours: int) -> Decimal:
    if request.day_part == "full":
        return Decimal(day_hours)
    if request.day_part == "hourly":
        return q(Decimal(request.hours_per_day or 0))
    return q(Decimal(day_hours) / 2)


@router.post("/leave-requests", response_model=LeaveRequestRead, status_code=201)
def create_leave_request(payload: LeaveRequestCreate, session: Session = Depends(get_session)):
    existing = session.scalar(
        select(LeaveRequest).where(LeaveRequest.idempotency_key == payload.idempotency_key)
    )
    if existing is not None:
        if (
            existing.employee_id != payload.employee_id
            or existing.start_date != payload.start_date
            or existing.end_date != payload.end_date
        ):
            raise ApiError("idempotency_conflict", "Bu anahtar farklı bir talepte kullanılmış.", 409)
        return _request_read(session, existing)
    employee = get_employee(session, payload.employee_id, allow_archived=False)
    leave_type = resolve_leave_type(session, payload.leave_type_id, payload.leave_type_code, default=None)
    if payload.day_part == "hourly":
        day_hours = load_settings(session).standard_day_hours
        assert payload.hours is not None
        if payload.hours > day_hours:
            raise ApiError(
                "invalid_hours", "Saatlik izin günlük normal süreyi aşamaz.", 422,
                {"standard_day_hours": day_hours},
            )
    if (
        employee.employment_start_date and payload.start_date < employee.employment_start_date
    ) or (employee.employment_end_date and payload.end_date > employee.employment_end_date):
        raise ApiError(
            "leave_outside_employment",
            "İzin tarihleri personelin işe giriş/çıkış aralığı dışında.",
            422,
            {
                "employment_start_date": employee.employment_start_date,
                "employment_end_date": employee.employment_end_date,
            },
        )
    overlap = session.scalars(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee.id,
            LeaveRequest.status == RecordStatus.ACTIVE,
            LeaveRequest.request_state.in_(("pending", "approved")),
            LeaveRequest.start_date <= payload.end_date,
            LeaveRequest.end_date >= payload.start_date,
        )
    ).first()
    if overlap is not None:
        raise ApiError(
            "leave_overlap",
            "Bu tarihlerde personelin bekleyen veya onaylı başka izin talebi var.",
            409,
            {"leave_request_id": overlap.id},
        )
    assert_range_unlocked(session, payload.start_date, payload.end_date, "İzin talebi")
    request = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        day_part=payload.day_part,
        hours_per_day=payload.hours,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
    )
    session.add(request)
    try:
        session.flush()
        add_audit(
            session, "leave_request", request.id, "created",
            {"employee_id": employee.id, "start": request.start_date, "end": request.end_date},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("idempotency_conflict", "Bu anahtar başka bir kayıtta kullanılmış.", 409) from exc
    session.refresh(request)
    return _request_read(session, request)


@router.get("/leave-requests", response_model=list[LeaveRequestRead])
def list_leave_requests(
    session: Session = Depends(get_session),
    employee_id: str | None = None,
    state: Literal["pending", "approved", "rejected", "cancelled"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(LeaveRequest).where(LeaveRequest.status == RecordStatus.ACTIVE)
    if employee_id:
        query = query.where(LeaveRequest.employee_id == employee_id)
    if state:
        query = query.where(LeaveRequest.request_state == state)
    if date_from:
        query = query.where(LeaveRequest.end_date >= date_from)
    if date_to:
        query = query.where(LeaveRequest.start_date <= date_to)
    rows = session.scalars(
        query.order_by(LeaveRequest.start_date.desc(), LeaveRequest.id).limit(limit).offset(offset)
    ).all()
    return [_request_read(session, r) for r in rows]


@router.get("/leave-requests/{request_id}", response_model=LeaveRequestRead)
def read_leave_request(request_id: str, session: Session = Depends(get_session)):
    return _request_read(session, _get_request(session, request_id))


def _invalid(request: LeaveRequest, target: str) -> ApiError:
    return ApiError(
        "invalid_transition",
        f"İzin talebi '{request.request_state}' durumundan '{target}' durumuna geçirilemez.",
        409,
        {"from": request.request_state, "to": target},
    )


def _finish(session: Session, request: LeaveRequest, target: str, note: str | None, detail: dict):
    request.request_state = target
    request.decided_at = datetime.now(UTC)
    request.decision_note = note
    add_audit(session, "leave_request", request.id, target, {"note": note, **detail})


def leave_amounts(
    employee: Employee, day: date, status: str, normal: Decimal, book, settings
) -> int:
    """Puantaj maliyeti: ücretli izin günü ve çalışılan saat için tarihte geçerli ücretle."""
    if normal <= 0:
        return 0
    rate = book.at(employee.id, day)
    if rate is None:
        raise ApiError(
            "missing_labor_rate",
            "Personelin izin gününde geçerli ücreti bulunmuyor; önce ücret kaydı ekleyin.",
            422,
            {"date": day},
        )
    return work_log_amount("worked", rate.rate_kurus, rate.wage_type, day, normal, Decimal(0), settings)


@router.post("/leave-requests/{request_id}/approve", response_model=LeaveRequestRead)
def approve_leave_request(
    request_id: str,
    payload: LeaveDecision | None = Body(default=None),
    session: Session = Depends(get_session),
):
    request = _get_request(session, request_id)
    if request.request_state != "pending":
        raise _invalid(request, "approved")
    employee = get_employee(session, request.employee_id, allow_archived=False)
    leave_type = session.get(LeaveType, request.leave_type_id)
    assert leave_type is not None
    settings = load_settings(session)
    day_hours = settings.standard_day_hours
    plans = PlanBook(session)
    holidays = holiday_dates(session, request.start_date, request.end_date)
    days, skipped = [], []
    cursor = request.start_date
    while cursor <= request.end_date:
        kind = day_classification(employee, cursor, plans, holidays)
        (days if kind == "workday" else skipped).append((cursor, kind))
        cursor += timedelta(days=1)
    if not days:
        raise ApiError(
            "leave_no_working_days",
            "İzin tarihlerinin tamamı resmî tatil veya haftalık izne denk geliyor.",
            422,
            {"skipped": [{"date": d, "day_type": k} for d, k in skipped]},
        )
    leave_days = [d for d, _ in days]
    existing = list(
        session.scalars(
            select(WorkLog).where(
                WorkLog.employee_id == employee.id,
                WorkLog.status == RecordStatus.ACTIVE,
                WorkLog.work_date.in_(leave_days),
            )
        )
    )
    if existing:
        raise ApiError(
            "attendance_conflict",
            "İzin günlerinde mevcut puantaj kaydı var; önce iptal edin veya düzeltin.",
            409,
            {"dates": sorted(log.work_date for log in existing)},
        )
    assert_dates_unlocked(session, leave_days, "İzin")

    per_day = _hours_per_day(request, day_hours)
    total = per_day * len(leave_days)
    allow_negative = load_attendance_settings(session).allow_negative_leave_balance
    if leave_type.deducts_entitlement:
        before = balance_for(session, employee.id, leave_type.id, leave_days[0])
        for day in leave_days:
            session.add(
                LeaveLedgerEntry(
                    employee_id=employee.id,
                    leave_type_id=leave_type.id,
                    entry_type="use",
                    quantity_hours=-per_day,
                    entry_date=day,
                    leave_request_id=request.id,
                    source="system",
                    idempotency_key=f"leave:{request.id}:{day.isoformat()}:use",
                    note="İzin kullanımı",
                )
            )
        session.flush()
        after = balance_for(session, employee.id, leave_type.id, leave_days[-1])
        if after["overdrawn_hours"] > before["overdrawn_hours"] and not allow_negative:
            raise _insufficient(before, total)

    book = load_rate_book(session, [employee.id])
    partial = per_day < day_hours
    created: list[WorkLog] = []
    for day in leave_days:
        paid_status = leave_type.work_status in PAID_STATUSES
        if paid_status:
            normal = Decimal(day_hours)  # ücretli izin saati + kalan (çalışıldı varsayılan) saat
        else:
            normal = Decimal(day_hours) - per_day if partial else Decimal(0)
        amount = leave_amounts(employee, day, leave_type.work_status, normal, book, settings)
        log = WorkLog(
            employee_id=employee.id,
            work_date=day,
            work_status=leave_type.work_status,
            normal_hours=q(normal),
            overtime_hours=Decimal("0.00"),
            hours=q(normal),
            calculated_amount_kurus=amount,
            manual_amount_kurus=None,
            amount_kurus=amount,
            leave_request_id=request.id,
            leave_hours=per_day,
            source="leave",
            note=f"İzin: {leave_type.name}",
        )
        session.add(log)
        created.append(log)
    request.total_hours = q(total)
    _finish(
        session, request, "approved", payload.note if payload else None,
        {"days": leave_days, "total_hours": q(total),
         "skipped": [{"date": d, "day_type": k} for d, k in skipped]},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            "attendance_conflict", "İzin günlerinde eş zamanlı bir puantaj kaydı oluştu.", 409
        ) from exc
    session.refresh(request)
    return _request_read(session, request)


@router.post("/leave-requests/{request_id}/reject", response_model=LeaveRequestRead)
def reject_leave_request(
    request_id: str,
    payload: LeaveDecision | None = Body(default=None),
    session: Session = Depends(get_session),
):
    request = _get_request(session, request_id)
    if request.request_state != "pending":
        raise _invalid(request, "rejected")
    _finish(session, request, "rejected", payload.note if payload else None, {})
    session.commit()
    session.refresh(request)
    return _request_read(session, request)


@router.post("/leave-requests/{request_id}/cancel", response_model=LeaveRequestRead)
def cancel_leave_request(
    request_id: str,
    payload: LeaveDecision | None = Body(default=None),
    session: Session = Depends(get_session),
):
    request = _get_request(session, request_id)
    if request.request_state not in ("pending", "approved"):
        raise _invalid(request, "cancelled")
    cancelled_logs: list[str] = []
    reversed_entries: list[str] = []
    if request.request_state == "approved":
        logs = list(
            session.scalars(
                select(WorkLog).where(
                    WorkLog.leave_request_id == request.id, WorkLog.status == RecordStatus.ACTIVE
                )
            )
        )
        assert_dates_unlocked(session, [log.work_date for log in logs], "İzin iptali")
        for log in logs:
            log.status = RecordStatus.CANCELLED
            cancelled_logs.append(log.id)
            add_audit(
                session, "work_log", log.id, "cancelled",
                {"amount_kurus": log.amount_kurus, "leave_request_id": request.id},
            )
        for use in session.scalars(
            select(LeaveLedgerEntry).where(
                LeaveLedgerEntry.leave_request_id == request.id,
                LeaveLedgerEntry.entry_type == "use",
                LeaveLedgerEntry.status == RecordStatus.ACTIVE,
            )
        ):
            reversal = LeaveLedgerEntry(
                employee_id=use.employee_id,
                leave_type_id=use.leave_type_id,
                entry_type="reversal",
                quantity_hours=-Decimal(use.quantity_hours),
                entry_date=use.entry_date,
                leave_request_id=request.id,
                reversed_entry_id=use.id,
                source="system",
                idempotency_key=f"reverse:{use.id}",
                note="İzin iptali",
            )
            session.add(reversal)
            reversed_entries.append(use.id)
    _finish(
        session, request, "cancelled", payload.note if payload else None,
        {"cancelled_work_logs": cancelled_logs, "reversed_use_entries": reversed_entries},
    )
    session.commit()
    session.refresh(request)
    return _request_read(session, request)

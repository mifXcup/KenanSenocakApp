"""Personel finans hareket defteri.

Model: her hareket pozitif tutarlı, değişmez bir satırdır. `direction` hareketin hangi borç havuzuna
(şirketin personele borcu / personelin şirkete borcu) yazıldığını gösterir. Artıran türler havuzu
büyütür, kapatan türler (ödeme, mahsup) aynı yöndeki havuzdan düşer. Ters kayıt orijinali değiştirmez;
ters satırı olan hareket "hükümsüz" sayılır (bir hareket yalnız bir kez terslenebilir).

Havuzlar:
- Şirket borcu: dönem tahakkuku (+ düzeltme) - o döneme yapılan maaş ödemeleri; dönemsiz açılış/düzeltme
  bakiyeleri ayrı tutulur ve maaş dönemi kalanına karışmaz.
- Personel borcu: avans havuzu (avans - maaştan avans mahsubu) ve borç havuzu (personel borcu + açılış +
  düzeltme - personel borç ödemeleri) ayrı hesaplanır; borç ödemesi maaş borcunu hiç azaltmaz.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_sidecar_token
from .attendance import load_attendance_settings, salary_due_date
from .database import get_session
from .employees import get_employee
from .models import (
    Employee,
    EmployeeFinancialMovement,
    PayrollEntry,
    PayrollPeriod,
    Project,
    RecordStatus,
    Site,
)
from .operations import validate_site_project
from .payroll import get_period
from .reports import AGING_LABELS, OVERDUE_KEYS, aging_bucket
from .schemas import OrmModel

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])

CO = "company_owes_employee"
EO = "employee_owes_company"
Direction = Literal["company_owes_employee", "employee_owes_company"]
MovementTypeName = Literal[
    "payroll_accrual",
    "payroll_payment",
    "advance",
    "employee_debt",
    "employee_debt_payment",
    "salary_deduction",
    "bonus",
    "additional_earning",
    "correction",
    "opening_balance",
    "reversal",
]
ALLOWED_DIRECTIONS = {
    "payroll_accrual": {CO},
    "payroll_payment": {CO},
    "advance": {EO},
    "employee_debt": {EO},
    "employee_debt_payment": {EO},
    "salary_deduction": {CO},
    "bonus": {CO},
    "additional_earning": {CO},
    "correction": {CO, EO},
    "opening_balance": {CO, EO},
}
PERIOD_INPUT_TYPES = {"bonus", "additional_earning", "salary_deduction"}
SYSTEM_ONLY_TYPES = {"payroll_accrual", "reversal"}
BUCKET_NAMES = {
    "not_due": "not_due",
    "d1_30": "1_30",
    "d31_60": "31_60",
    "d61_90": "61_90",
    "d90_plus": "90_plus",
    "no_due_date": "no_due_date",
}
OVERDUE_NAMES = {BUCKET_NAMES[key] for key in OVERDUE_KEYS}
LEGACY_TYPES = {"advance": "advance", "payroll_payment": "wage"}


def classify(movement: EmployeeFinancialMovement) -> str | None:
    kind = (movement.movement_type, movement.direction)
    return {
        ("payroll_accrual", CO): "accrual",
        ("payroll_payment", CO): "paid",
        ("advance", EO): "advance",
        ("salary_deduction", EO): "advance_offset",
        ("salary_deduction", CO): "input_deduction",
        ("bonus", CO): "input_bonus",
        ("additional_earning", CO): "input_additional",
        ("employee_debt", EO): "debt_inc",
        ("employee_debt_payment", EO): "debt_dec",
        ("correction", CO): "corr_co",
        ("correction", EO): "debt_inc",
        ("opening_balance", CO): "open_co",
        ("opening_balance", EO): "debt_inc",
    }.get(kind)


# (company_owes delta, employee_owes delta) işareti; girdi türleri bakiyeyi etkilemez.
DELTAS = {
    "accrual": (1, 0),
    "paid": (-1, 0),
    "corr_co": (1, 0),
    "open_co": (1, 0),
    "advance": (0, 1),
    "advance_offset": (0, -1),
    "debt_inc": (0, 1),
    "debt_dec": (0, -1),
}


@dataclass
class Item:
    side: str
    kind: str
    movement: EmployeeFinancialMovement
    remaining: int


@dataclass
class Position:
    employee_id: str
    co_items: list[Item] = field(default_factory=list)
    advance_items: list[Item] = field(default_factory=list)
    debt_items: list[Item] = field(default_factory=list)
    period_remaining: dict[str | None, int] = field(default_factory=dict)
    period_paid: dict[str, int] = field(default_factory=dict)
    period_corrections: dict[str, int] = field(default_factory=dict)

    @property
    def unpaid_payroll(self) -> int:
        return sum(v for k, v in self.period_remaining.items() if k is not None)

    @property
    def unscoped_co(self) -> int:
        return self.period_remaining.get(None, 0)

    @property
    def company_owes(self) -> int:
        return self.unpaid_payroll + self.unscoped_co

    @property
    def advance_pool(self) -> int:
        return sum(i.remaining for i in self.advance_items)

    @property
    def debt_pool(self) -> int:
        return sum(i.remaining for i in self.debt_items)

    @property
    def employee_owes(self) -> int:
        return self.advance_pool + self.debt_pool

    def all_items(self) -> list[Item]:
        return [i for i in self.co_items + self.advance_items + self.debt_items if i.remaining > 0]


def _fifo(items: list[Item], settled: int) -> None:
    items.sort(
        key=lambda i: (
            i.movement.due_date or date.max,
            i.movement.movement_date,
            i.movement.created_at,
            i.movement.id,
        )
    )
    for item in items:
        used = min(item.remaining, settled)
        item.remaining -= used
        settled -= used


def load_effective(
    session: Session, employee_ids: list[str] | None, as_of: date | None
) -> dict[str, list[EmployeeFinancialMovement]]:
    """Hükümsüz (terslenmiş) ve ters satırlar çıkarılmış, as_of tarihine kadarki hareketler."""
    query = select(EmployeeFinancialMovement).where(
        EmployeeFinancialMovement.status == RecordStatus.ACTIVE
    )
    if employee_ids is not None:
        if not employee_ids:
            return {}
        query = query.where(EmployeeFinancialMovement.employee_id.in_(employee_ids))
    if as_of is not None:
        query = query.where(EmployeeFinancialMovement.movement_date <= as_of)
    rows = session.scalars(query).all()
    voided = {r.reversed_movement_id for r in rows if r.movement_type == "reversal"}
    grouped: dict[str, list[EmployeeFinancialMovement]] = defaultdict(list)
    for row in rows:
        if row.movement_type != "reversal" and row.id not in voided:
            grouped[row.employee_id].append(row)
    return grouped


def build_position(employee_id: str, movements: list[EmployeeFinancialMovement]) -> Position:
    position = Position(employee_id=employee_id)
    scoped_items: dict[str | None, list[Item]] = defaultdict(list)
    paid: dict[str | None, int] = defaultdict(int)
    offsets = debt_paid = 0
    for movement in movements:
        kind = classify(movement)
        amount = movement.amount_kurus
        scope = movement.payroll_period_id
        if kind in {"accrual", "corr_co", "open_co"}:
            item = Item(CO, kind, movement, amount)
            scoped_items[scope].append(item)
            position.co_items.append(item)
            if kind == "corr_co" and scope:
                position.period_corrections[scope] = position.period_corrections.get(scope, 0) + amount
        elif kind == "paid":
            paid[scope] += amount
            if scope:
                position.period_paid[scope] = position.period_paid.get(scope, 0) + amount
        elif kind == "advance":
            position.advance_items.append(Item(EO, kind, movement, amount))
        elif kind == "advance_offset":
            offsets += amount
        elif kind == "debt_inc":
            position.debt_items.append(Item(EO, kind, movement, amount))
        elif kind == "debt_dec":
            debt_paid += amount
    for scope, items in scoped_items.items():
        _fifo(items, paid.get(scope, 0))
        position.period_remaining[scope] = sum(i.remaining for i in items)
    _fifo(position.advance_items, offsets)
    _fifo(position.debt_items, debt_paid)
    return position


def compute_positions(
    session: Session, employee_ids: list[str] | None = None, as_of: date | None = None
) -> dict[str, Position]:
    grouped = load_effective(session, employee_ids, as_of)
    ids = employee_ids if employee_ids is not None else list(grouped)
    return {eid: build_position(eid, grouped.get(eid, [])) for eid in ids}


def aging_rows(position: Position, as_of: date) -> list[dict]:
    rows = []
    for item in position.all_items():
        bucket, days = aging_bucket(item.movement.due_date, as_of)
        rows.append(
            {
                "side": item.side,
                "movement_id": item.movement.id,
                "employee_id": position.employee_id,
                "movement_type": item.movement.movement_type,
                "movement_date": item.movement.movement_date,
                "due_date": item.movement.due_date,
                "payroll_period_id": item.movement.payroll_period_id,
                "remaining_kurus": item.remaining,
                "bucket": BUCKET_NAMES[bucket],
                "days_overdue": days,
            }
        )
    rows.sort(
        key=lambda r: (r["side"], r["due_date"] or date.max, r["movement_date"], r["movement_id"])
    )
    return rows


def summarize(position: Position, as_of: date) -> dict:
    rows = aging_rows(position, as_of)

    def overdue(side: str) -> int:
        return sum(r["remaining_kurus"] for r in rows if r["side"] == side and r["bucket"] in OVERDUE_NAMES)

    opening_co = sum(
        i.remaining for i in position.co_items if i.kind == "open_co" or (i.kind == "corr_co" and not i.movement.payroll_period_id)
    )
    return {
        "as_of": as_of,
        "company_owes_employee_kurus": position.company_owes,
        "employee_owes_company_kurus": position.employee_owes,
        "unpaid_payroll_kurus": position.unpaid_payroll,
        "active_advance_kurus": position.advance_pool,
        "overdue_company_debt_kurus": overdue(CO),
        "overdue_employee_debt_kurus": overdue(EO),
        "employee_debt_kurus": position.debt_pool,
        "opening_and_correction_company_kurus": opening_co,
        "net_position_kurus": position.company_owes - position.employee_owes,
    }


def aging_summary(rows: list[dict]) -> dict:
    def side(name: str) -> list[dict]:
        buckets = {BUCKET_NAMES[k]: [0, 0] for k in AGING_LABELS}
        for row in rows:
            if row["side"] == name:
                buckets[row["bucket"]][0] += row["remaining_kurus"]
                buckets[row["bucket"]][1] += 1
        return [
            {"bucket": key, "amount_kurus": value[0], "count": value[1]}
            for key, value in buckets.items()
        ]

    return {"company_owes_employee": side(CO), "employee_owes_company": side(EO)}


# --- Dönem bağlantıları (payroll.py kancalarını doldurur) -------------------------------------------


def gather_period_inputs(session: Session, period: PayrollPeriod) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = defaultdict(lambda: {"bonus": 0, "additional": 0, "deduction": 0})
    effective = load_effective(session, None, None)
    key = {"input_bonus": "bonus", "input_additional": "additional", "input_deduction": "deduction"}
    for employee_id, movements in effective.items():
        for movement in movements:
            if movement.payroll_period_id != period.id:
                continue
            kind = classify(movement)
            if kind in key:
                result[employee_id][key[kind]] += movement.amount_kurus
    return dict(result)


def advance_pools_as_of(session: Session, employee_ids: list[str], as_of: date) -> dict[str, int]:
    return {
        eid: pos.advance_pool for eid, pos in compute_positions(session, employee_ids, as_of).items()
    }


def refresh_balances(session: Session, period: PayrollPeriod) -> None:
    entries = list(
        session.scalars(select(PayrollEntry).where(PayrollEntry.payroll_period_id == period.id))
    )
    ids = [e.employee_id for e in entries]
    positions = compute_positions(session, ids)
    for entry in entries:
        pos = positions[entry.employee_id]
        entry.paid_kurus = pos.period_paid.get(period.id, 0)
        entry.remaining_kurus = (
            entry.net_due_kurus + pos.period_corrections.get(period.id, 0) - entry.paid_kurus
        )


def post_ledger_on_finalize(
    session: Session, period: PayrollPeriod, entries: list[PayrollEntry], due: date | None
) -> None:
    # Vade: istekte açık tarih > personel maaş günü istisnası > şirket varsayılanı > dönem bitişi.
    attendance = load_attendance_settings(session)
    people = {
        e.id: e
        for e in session.scalars(
            select(Employee).where(Employee.id.in_([x.employee_id for x in entries] or [""]))
        )
    }
    for entry in entries:
        if entry.net_due_kurus > 0:
            entry_due = due or salary_due_date(
                people.get(entry.employee_id), period.period_end, attendance
            )
            session.add(
                EmployeeFinancialMovement(
                    employee_id=entry.employee_id,
                    payroll_period_id=period.id,
                    movement_date=period.period_end,
                    movement_type="payroll_accrual",
                    direction=CO,
                    amount_kurus=entry.net_due_kurus,
                    due_date=entry_due or period.period_end,
                    note=f"Maaş tahakkuku: {period.title}",
                    idempotency_key=f"payroll:{period.id}:{entry.employee_id}:accrual",
                    source="system",
                )
            )
        if entry.advance_deduction_kurus > 0:
            session.add(
                EmployeeFinancialMovement(
                    employee_id=entry.employee_id,
                    payroll_period_id=period.id,
                    movement_date=period.period_end,
                    movement_type="salary_deduction",
                    direction=EO,
                    amount_kurus=entry.advance_deduction_kurus,
                    note=f"Avans mahsubu: {period.title}",
                    idempotency_key=f"payroll:{period.id}:{entry.employee_id}:advance-offset",
                    source="system",
                )
            )
    session.flush()


def install_payroll_hooks() -> None:
    from . import payroll

    payroll.gather_inputs = gather_period_inputs
    payroll.advance_pools = advance_pools_as_of
    payroll.post_finalize_ledger = post_ledger_on_finalize
    payroll.refresh_entry_balances = refresh_balances


install_payroll_hooks()


# --- Şemalar --------------------------------------------------------------------------------------


class MovementCreate(BaseModel):
    employee_id: str
    payroll_period_id: str | None = None
    project_id: str | None = None
    site_id: str | None = None
    movement_date: date
    movement_type: MovementTypeName
    direction: Direction | None = None
    amount_kurus: int = Field(gt=0)
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def validate_movement(self) -> MovementCreate:
        if self.movement_type in SYSTEM_ONLY_TYPES:
            raise ValueError("Bu hareket türü yalnız sistem veya ters kayıt ile oluşur.")
        allowed = ALLOWED_DIRECTIONS[self.movement_type]
        if self.direction is None:
            if len(allowed) != 1:
                raise ValueError("Bu hareket türü için direction belirtilmelidir.")
            self.direction = next(iter(allowed))  # type: ignore[assignment]
        if self.direction not in allowed:
            raise ValueError("Bu hareket türü için geçersiz direction.")
        if self.due_date is not None and self.due_date < self.movement_date:
            raise ValueError("Vade tarihi hareket tarihinden önce olamaz.")
        return self


class MovementRead(OrmModel):
    id: str
    employee_id: str
    payroll_period_id: str | None
    project_id: str | None
    site_id: str | None
    movement_date: date
    movement_type: str
    direction: str
    amount_kurus: int
    due_date: date | None
    note: str | None
    idempotency_key: str
    reversed_movement_id: str | None
    source: str
    status: RecordStatus
    voided: bool = False
    overpayment_movement_id: str | None = None


class ReverseRequest(BaseModel):
    movement_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


# --- Hareket oluşturma ----------------------------------------------------------------------------


def _read(movement: EmployeeFinancialMovement, voided: bool = False) -> MovementRead:
    read = MovementRead.model_validate(movement)
    read.voided = voided
    return read


def _voided_ids(session: Session, movement_ids: list[str]) -> set[str]:
    if not movement_ids:
        return set()
    return set(
        session.scalars(
            select(EmployeeFinancialMovement.reversed_movement_id).where(
                EmployeeFinancialMovement.reversed_movement_id.in_(movement_ids)
            )
        )
    )


def _new_movement(session: Session, **values) -> EmployeeFinancialMovement:
    movement = EmployeeFinancialMovement(**values)
    session.add(movement)
    session.flush()
    add_audit(
        session,
        "employee_financial_movement",
        movement.id,
        "created",
        {
            "employee_id": movement.employee_id,
            "type": movement.movement_type,
            "direction": movement.direction,
            "amount_kurus": movement.amount_kurus,
            "payroll_period_id": movement.payroll_period_id,
        },
    )
    return movement


def create_movement(session: Session, payload: MovementCreate) -> MovementRead:
    existing = session.scalar(
        select(EmployeeFinancialMovement).where(
            EmployeeFinancialMovement.idempotency_key == payload.idempotency_key
        )
    )
    if existing is not None:
        if existing.employee_id != payload.employee_id:
            raise ApiError("idempotency_conflict", "Bu anahtar başka bir kayıtta kullanılmış.", 409)
        return _read(existing, existing.id in _voided_ids(session, [existing.id]))

    employee = get_employee(session, payload.employee_id)
    if payload.project_id and session.get(Project, payload.project_id) is None:
        raise ApiError("not_found", "Proje bulunamadı.", 404)
    if payload.site_id:
        site = session.get(Site, payload.site_id)
        if site is None:
            raise ApiError("not_found", "Şantiye bulunamadı.", 404)
        validate_site_project(site, payload.project_id)

    kind = payload.movement_type
    period: PayrollPeriod | None = None
    if payload.payroll_period_id:
        period = get_period(session, payload.payroll_period_id)
    if kind in PERIOD_INPUT_TYPES:
        if period is None:
            raise ApiError("period_required", "Bu hareket için maaş dönemi seçilmelidir.", 422)
        if period.state not in ("draft", "calculated"):
            raise ApiError(
                "period_locked",
                "Kesinleşmiş döneme girdi eklenemez; düzeltme hareketi kullanın.",
                409,
            )
    elif kind == "correction":
        if period is not None and period.state not in ("finalized", "closed"):
            raise ApiError(
                "period_not_finalized",
                "Dönem bağlı düzeltme yalnız kesinleşmiş döneme yapılır.",
                409,
            )
    elif kind != "payroll_payment" and period is not None:
        raise ApiError("period_not_allowed", "Bu hareket bir maaş dönemine bağlanamaz.", 422)

    values = {
        "employee_id": employee.id,
        "payroll_period_id": payload.payroll_period_id,
        "project_id": payload.project_id,
        "site_id": payload.site_id,
        "movement_date": payload.movement_date,
        "movement_type": kind,
        "direction": payload.direction,
        "amount_kurus": payload.amount_kurus,
        "due_date": payload.due_date,
        "note": payload.note,
        "idempotency_key": payload.idempotency_key,
    }
    overpayment: EmployeeFinancialMovement | None = None
    if kind == "payroll_payment":
        movement, overpayment = _pay_payroll(session, employee, period, payload, values)
    else:
        if kind == "employee_debt_payment":
            pool = compute_positions(session, [employee.id])[employee.id].debt_pool
            if payload.amount_kurus > pool:
                raise ApiError(
                    "overpayment",
                    "Borç ödemesi personelin kalan borcunu aşıyor.",
                    409,
                    {"remaining_kurus": pool},
                )
        movement = _new_movement(session, **values)
    if period is not None:
        refresh_balances(session, period)
    read = _read(movement)
    if overpayment is not None:
        read.overpayment_movement_id = overpayment.id
    return read


def _pay_payroll(
    session: Session,
    employee: Employee,
    period: PayrollPeriod | None,
    payload: MovementCreate,
    values: dict,
) -> tuple[EmployeeFinancialMovement, EmployeeFinancialMovement | None]:
    position = compute_positions(session, [employee.id])[employee.id]
    if period is not None:
        if period.state == "closed":
            raise ApiError("period_locked", "Kapanmış döneme ödeme yapılamaz.", 409)
        if period.state != "finalized":
            raise ApiError(
                "period_not_finalized", "Ödeme için dönem kesinleştirilmiş olmalıdır.", 409
            )
        entry = session.scalar(
            select(PayrollEntry).where(
                PayrollEntry.payroll_period_id == period.id,
                PayrollEntry.employee_id == employee.id,
                PayrollEntry.status == RecordStatus.ACTIVE,
            )
        )
        if entry is None:
            raise ApiError("not_found", "Personelin bu dönemde maaş kaydı yok.", 404)
        outstanding = position.period_remaining.get(period.id, 0)
    else:
        outstanding = position.unscoped_co
    applied = min(payload.amount_kurus, outstanding)
    excess = payload.amount_kurus - applied
    primary: EmployeeFinancialMovement | None = None
    if applied > 0:
        primary = _new_movement(session, **{**values, "amount_kurus": applied})
    overpayment: EmployeeFinancialMovement | None = None
    if excess > 0:
        # Fazla ödeme açıkça avans (personelden alacak) olarak görünür.
        overpayment = _new_movement(
            session,
            **{
                **values,
                "movement_type": "advance",
                "direction": EO,
                "payroll_period_id": None,
                "amount_kurus": excess,
                "idempotency_key": f"{payload.idempotency_key}:overpayment",
                "note": "Fazla ödeme: avans/alacak olarak kaydedildi"
                + (f" ({payload.note})" if payload.note else ""),
                "source": "system",
            },
        )
    return (primary or overpayment), (overpayment if primary else None)  # type: ignore[return-value]


@router.post("/employee-finance/movements", response_model=MovementRead, status_code=201)
def post_movement(payload: MovementCreate, session: Session = Depends(get_session)):
    try:
        result = create_movement(session, payload)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("duplicate_movement", "Aynı hareket zaten kaydedilmiş.", 409) from exc
    return result


@router.get("/employee-finance/movements", response_model=list[MovementRead])
def list_movements(
    session: Session = Depends(get_session),
    employee_id: str | None = None,
    payroll_period_id: str | None = None,
    project_id: str | None = None,
    site_id: str | None = None,
    movement_type: str | None = Query(default=None, pattern="^[a-z_]{1,24}$"),
    date_from: date | None = None,
    date_to: date | None = None,
    include_reversals: bool = True,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(EmployeeFinancialMovement).where(
        EmployeeFinancialMovement.status == RecordStatus.ACTIVE
    )
    for column, value in (
        (EmployeeFinancialMovement.employee_id, employee_id),
        (EmployeeFinancialMovement.payroll_period_id, payroll_period_id),
        (EmployeeFinancialMovement.project_id, project_id),
        (EmployeeFinancialMovement.site_id, site_id),
        (EmployeeFinancialMovement.movement_type, movement_type),
    ):
        if value:
            query = query.where(column == value)
    if date_from:
        query = query.where(EmployeeFinancialMovement.movement_date >= date_from)
    if date_to:
        query = query.where(EmployeeFinancialMovement.movement_date <= date_to)
    if not include_reversals:
        query = query.where(EmployeeFinancialMovement.movement_type != "reversal")
    rows = list(
        session.scalars(
            query.order_by(
                EmployeeFinancialMovement.movement_date.desc(),
                EmployeeFinancialMovement.created_at.desc(),
                EmployeeFinancialMovement.id,
            )
            .limit(limit)
            .offset(offset)
        )
    )
    voided = _voided_ids(session, [r.id for r in rows])
    return [_read(r, r.id in voided) for r in rows]


def reverse_movement(
    session: Session, movement_id: str, payload: ReverseRequest
) -> EmployeeFinancialMovement:
    original = session.get(EmployeeFinancialMovement, movement_id)
    if original is None or original.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "Hareket bulunamadı.", 404)
    if original.movement_type == "reversal":
        raise ApiError("cannot_reverse_reversal", "Ters kayıt tekrar terslenemez.", 409)
    if original.source == "system":
        raise ApiError(
            "system_movement",
            "Sistem hareketi terslenemez; düzeltme hareketi kullanın.",
            409,
        )
    if session.scalar(
        select(EmployeeFinancialMovement.id).where(
            EmployeeFinancialMovement.reversed_movement_id == original.id
        )
    ):
        raise ApiError("already_reversed", "Bu hareket zaten terslenmiş.", 409)
    period = (
        session.get(PayrollPeriod, original.payroll_period_id)
        if original.payroll_period_id
        else None
    )
    if period is not None:
        if original.movement_type in PERIOD_INPUT_TYPES and period.state not in (
            "draft",
            "calculated",
        ):
            raise ApiError(
                "period_locked",
                "Kesinleşmiş dönemin girdisi terslenemez; düzeltme hareketi kullanın.",
                409,
            )
        if original.movement_type == "payroll_payment" and period.state == "closed":
            raise ApiError("period_locked", "Kapanmış dönemin ödemesi terslenemez.", 409)
    reversal = _new_movement(
        session,
        employee_id=original.employee_id,
        payroll_period_id=original.payroll_period_id,
        project_id=original.project_id,
        site_id=original.site_id,
        movement_date=payload.movement_date or date.today(),
        movement_type="reversal",
        direction=EO if original.direction == CO else CO,
        amount_kurus=original.amount_kurus,
        note=payload.note or f"Ters kayıt: {original.movement_type}",
        idempotency_key=f"reversal:{original.id}",
        reversed_movement_id=original.id,
        source="manual",
    )
    add_audit(
        session,
        "employee_financial_movement",
        original.id,
        "reversed",
        {"reversal_id": reversal.id, "amount_kurus": original.amount_kurus},
    )
    if period is not None:
        refresh_balances(session, period)
    return reversal


@router.post("/employee-finance/movements/{movement_id}/reverse", response_model=MovementRead)
def post_reverse(
    movement_id: str,
    payload: ReverseRequest = Body(default_factory=ReverseRequest),
    session: Session = Depends(get_session),
):
    try:
        reversal = reverse_movement(session, movement_id, payload)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("already_reversed", "Bu hareket zaten terslenmiş.", 409) from exc
    return _read(reversal)


# --- Özet, ekstre, yaşlandırma ----------------------------------------------------------------------


class FinancialSummary(BaseModel):
    employee_id: str
    as_of: date
    company_owes_employee_kurus: int
    employee_owes_company_kurus: int
    unpaid_payroll_kurus: int
    active_advance_kurus: int
    overdue_company_debt_kurus: int
    overdue_employee_debt_kurus: int
    employee_debt_kurus: int
    opening_and_correction_company_kurus: int
    net_position_kurus: int


def employee_summary(session: Session, employee_id: str, as_of: date) -> dict:
    position = compute_positions(session, [employee_id], as_of)[employee_id]
    return summarize(position, as_of)


@router.get("/employees/{employee_id}/financial-summary", response_model=FinancialSummary)
def financial_summary(
    employee_id: str, as_of: date | None = None, session: Session = Depends(get_session)
):
    get_employee(session, employee_id)
    day = as_of or date.today()
    return FinancialSummary(employee_id=employee_id, **employee_summary(session, employee_id, day))


def statement_lines(
    session: Session,
    employee_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[dict], dict]:
    rows = list(
        session.scalars(
            select(EmployeeFinancialMovement)
            .where(
                EmployeeFinancialMovement.employee_id == employee_id,
                EmployeeFinancialMovement.status == RecordStatus.ACTIVE,
            )
            .order_by(
                EmployeeFinancialMovement.movement_date,
                EmployeeFinancialMovement.created_at,
                EmployeeFinancialMovement.id,
            )
        )
    )
    by_id = {r.id: r for r in rows}
    voided = {r.reversed_movement_id for r in rows if r.movement_type == "reversal"}
    running_co = running_eo = 0
    lines: list[dict] = []
    for row in rows:
        source = by_id.get(row.reversed_movement_id) if row.movement_type == "reversal" else row
        kind = classify(source) if source is not None else None
        sign = -1 if row.movement_type == "reversal" else 1
        co_sign, eo_sign = DELTAS.get(kind or "", (0, 0))
        co_delta = sign * co_sign * row.amount_kurus
        eo_delta = sign * eo_sign * row.amount_kurus
        running_co += co_delta
        running_eo += eo_delta
        if (date_from and row.movement_date < date_from) or (date_to and row.movement_date > date_to):
            continue
        lines.append(
            {
                "movement_id": row.id,
                "movement_date": row.movement_date,
                "movement_type": row.movement_type,
                "direction": row.direction,
                "payroll_period_id": row.payroll_period_id,
                "amount_kurus": row.amount_kurus,
                "due_date": row.due_date,
                "note": row.note,
                "voided": row.id in voided,
                "informational": kind in {"input_bonus", "input_additional", "input_deduction"},
                "company_owes_delta_kurus": co_delta,
                "employee_owes_delta_kurus": eo_delta,
                "running_company_owes_kurus": running_co,
                "running_employee_owes_kurus": running_eo,
            }
        )
    totals = {
        "company_owes_delta_kurus": sum(line["company_owes_delta_kurus"] for line in lines),
        "employee_owes_delta_kurus": sum(line["employee_owes_delta_kurus"] for line in lines),
        "closing_company_owes_kurus": running_co,
        "closing_employee_owes_kurus": running_eo,
    }
    return lines, totals


@router.get("/employees/{employee_id}/statement")
def employee_statement(
    employee_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    employee = get_employee(session, employee_id)
    lines, totals = statement_lines(session, employee_id, date_from, date_to)
    return {
        "employee_id": employee.id,
        "employee_name": employee.name,
        "date_from": date_from,
        "date_to": date_to,
        "line_count": len(lines),
        "totals": totals,
        "lines": lines[offset : offset + limit],
    }


@router.get("/employees/{employee_id}/debt-aging")
def employee_debt_aging(
    employee_id: str, as_of: date | None = None, session: Session = Depends(get_session)
):
    get_employee(session, employee_id)
    day = as_of or date.today()
    position = compute_positions(session, [employee_id], day)[employee_id]
    rows = aging_rows(position, day)
    return {"employee_id": employee_id, "as_of": day, **aging_summary(rows), "items": rows}


# --- v0.2.0 /employee-payments uyumluluk katmanı ------------------------------------------------------


class LegacyPaymentCreate(BaseModel):
    employee_id: str
    payment_date: date
    amount_kurus: int = Field(gt=0)
    payment_type: Literal["advance", "wage"]
    note: str | None = Field(default=None, max_length=2000)


class LegacyPaymentRead(BaseModel):
    id: str
    employee_id: str
    payment_date: date
    amount_kurus: int
    payment_type: str
    note: str | None
    status: str


def _legacy(movement: EmployeeFinancialMovement, voided: bool) -> LegacyPaymentRead:
    return LegacyPaymentRead(
        id=movement.id,
        employee_id=movement.employee_id,
        payment_date=movement.movement_date,
        amount_kurus=movement.amount_kurus,
        payment_type=LEGACY_TYPES[movement.movement_type],
        note=movement.note,
        status="reversed" if voided else "active",
    )


@router.post("/employee-payments", response_model=LegacyPaymentRead, status_code=201)
def create_employee_payment(payload: LegacyPaymentCreate, session: Session = Depends(get_session)):
    from uuid import uuid4

    result = create_movement(
        session,
        MovementCreate(
            employee_id=payload.employee_id,
            movement_date=payload.payment_date,
            movement_type="advance" if payload.payment_type == "advance" else "payroll_payment",
            amount_kurus=payload.amount_kurus,
            note=payload.note,
            idempotency_key=f"legacy-api:{uuid4()}",
        ),
    )
    session.commit()
    movement = session.get(EmployeeFinancialMovement, result.id)
    assert movement is not None
    return _legacy(movement, False)


@router.get("/employee-payments", response_model=list[LegacyPaymentRead])
def list_employee_payments(
    session: Session = Depends(get_session),
    employee_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(EmployeeFinancialMovement).where(
        EmployeeFinancialMovement.status == RecordStatus.ACTIVE,
        EmployeeFinancialMovement.movement_type.in_(list(LEGACY_TYPES)),
    )
    if employee_id:
        query = query.where(EmployeeFinancialMovement.employee_id == employee_id)
    rows = list(
        session.scalars(
            query.order_by(
                EmployeeFinancialMovement.movement_date.desc(),
                EmployeeFinancialMovement.created_at.desc(),
                EmployeeFinancialMovement.id,
            )
            .limit(limit)
            .offset(offset)
        )
    )
    voided = _voided_ids(session, [r.id for r in rows])
    return [_legacy(r, r.id in voided) for r in rows]


@router.post("/employee-payments/{payment_id}/reverse", response_model=LegacyPaymentRead)
def reverse_employee_payment(payment_id: str, session: Session = Depends(get_session)):
    original = session.get(EmployeeFinancialMovement, payment_id)
    if original is None or original.movement_type not in LEGACY_TYPES:
        raise ApiError("not_found", "Personel ödemesi bulunamadı.", 404)
    reverse_movement(session, payment_id, ReverseRequest())
    session.commit()
    return _legacy(original, True)

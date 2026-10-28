"""Müşteri kartı, alacak planı, tahsilat dağıtımı ve değişmez müşteri cari defteri.

Defter modeli: her hareket pozitif tutarlı, değişmez bir satırdır. `direction` müşterinin bize olan
alacağını artırır (`receivable_increase`: tahakkuk, açılış, iade, artıran düzeltme) veya azaltır
(`receivable_decrease`: tahsilat, azaltan düzeltme). Ters kayıt orijinali değiştirmez; zıt yönde yeni
satır yazar ve orijinali "hükümsüz" kılar (bir hareket yalnız bir kez terslenebilir).

Alacak planı (`receivable_schedules`) bir defter hareketi değil beklentidir. Tahsilat plana
`customer_payment_allocations` ile dağıtılır (çoktan çoğa; iptal edilebilir). Dağıtılmamış tahsilat
yaşlandırmada en eski vadeden düşülür. Tahsilat açık alacağı aşabilir: fazlası müşteri avansı
(`credit_kurus`) olarak görünür ve sonradan tahakkuk/plana dağıtılabilir.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import clock
from .api import ApiError, add_audit, require_sidecar_token
from .database import get_session
from .models import (
    Customer,
    CustomerFinancialMovement,
    CustomerPaymentAllocation,
    Project,
    ProjectChangeOrder,
    ReceivableSchedule,
    RecordStatus,
)
from .reports import aging_bucket
from .schemas import OrmModel

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])

INCREASE = "receivable_increase"
DECREASE = "receivable_decrease"
Direction = Literal["receivable_increase", "receivable_decrease"]
MovementTypeName = Literal[
    "accrual", "opening_balance", "collection", "refund", "correction", "reversal"
]
ALLOWED_DIRECTIONS: dict[str, set[str]] = {
    "accrual": {INCREASE},
    "opening_balance": {INCREASE},
    "collection": {DECREASE},
    "refund": {INCREASE},
    "correction": {INCREASE, DECREASE},
}
AGING_NAMES = {
    "not_due": "not_due",
    "d1_30": "1_30",
    "d31_60": "31_60",
    "d61_90": "61_90",
    "d90_plus": "90_plus",
    "no_due_date": "no_due_date",
}
OVERDUE_NAMES = {"1_30", "31_60", "61_90", "90_plus"}
_TR_LOWER = str.maketrans({"İ": "i", "I": "ı"})


def normalize_customer_name(name: str) -> str:
    """Türkçe İ/ı ayrımını koruyan, boşlukları sadeleştirilmiş küçük harfli ad."""
    return " ".join(name.split()).translate(_TR_LOWER).casefold()


# --- Müşteri kartı ----------------------------------------------------------------------------------


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=2000)
    contact_person: str | None = Field(default=None, max_length=180)
    note: str | None = Field(default=None, max_length=2000)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=2000)
    contact_person: str | None = Field(default=None, max_length=180)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_patch(self) -> CustomerUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Müşteri adı boş bırakılamaz.")
        return self


class CustomerRead(OrmModel):
    id: str
    name: str
    phone: str | None
    address: str | None
    contact_person: str | None
    note: str | None
    status: RecordStatus


class CustomerDetail(CustomerRead):
    receivable_kurus: int
    credit_kurus: int
    net_balance_kurus: int
    balance_kurus: int  # net_balance_kurus ile aynı (geriye uyumluluk)
    unallocated_collection_kurus: int
    project_count: int


def get_customer(session: Session, customer_id: str) -> Customer:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise ApiError("not_found", "Müşteri bulunamadı.", 404)
    return customer


def require_open_customer(session: Session, customer_id: str) -> Customer:
    customer = get_customer(session, customer_id)
    if customer.status != RecordStatus.ACTIVE:
        raise ApiError("customer_archived", "Arşivlenmiş müşteriye yeni kayıt eklenemez.", 409)
    return customer


def find_or_create_customer(session: Session, name: str) -> Customer:
    """Proje müşteri adından müşteri kartını bulur; yoksa oluşturur (arşivli kart yeniden kullanılır)."""
    normalized = normalize_customer_name(name)
    customer = session.scalar(select(Customer).where(Customer.normalized_name == normalized))
    if customer is None:
        customer = Customer(name=" ".join(name.split()), normalized_name=normalized)
        session.add(customer)
        session.flush()
        add_audit(session, "customer", customer.id, "created", {"source": "project"})
    return customer


def _customer_detail(session: Session, customer: Customer) -> CustomerDetail:
    projects = int(
        session.scalar(
            select(func.count(Project.id)).where(
                Project.customer_id == customer.id, Project.status == RecordStatus.ACTIVE
            )
        )
        or 0
    )
    position = customer_position(session, customer.id)
    return CustomerDetail(
        **CustomerRead.model_validate(customer).model_dump(),
        **position,
        balance_kurus=position["net_balance_kurus"],
        project_count=projects,
    )


@router.post("/customers", response_model=CustomerRead, status_code=201)
def create_customer(payload: CustomerCreate, session: Session = Depends(get_session)):
    customer = Customer(
        **{**payload.model_dump(), "name": " ".join(payload.name.split())},
        normalized_name=normalize_customer_name(payload.name),
    )
    session.add(customer)
    try:
        session.flush()
        add_audit(session, "customer", customer.id, "created")
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("duplicate_customer", "Bu müşteri zaten kayıtlı.", 409) from exc
    session.refresh(customer)
    return customer


@router.get("/customers", response_model=list[CustomerRead])
def list_customers(
    session: Session = Depends(get_session),
    q: str | None = Query(default=None, max_length=100),
    include_archived: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(Customer)
    if not include_archived:
        query = query.where(Customer.status == RecordStatus.ACTIVE)
    if q:
        query = query.where(Customer.normalized_name.contains(normalize_customer_name(q)))
    return session.scalars(query.order_by(Customer.normalized_name).limit(limit).offset(offset)).all()


@router.get("/customers/{customer_id}", response_model=CustomerDetail)
def read_customer(customer_id: str, session: Session = Depends(get_session)):
    return _customer_detail(session, get_customer(session, customer_id))


@router.patch("/customers/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: str, payload: CustomerUpdate, session: Session = Depends(get_session)
):
    customer = require_open_customer(session, customer_id)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = " ".join(changes["name"].split())
        customer.normalized_name = normalize_customer_name(changes["name"])
    before = {key: getattr(customer, key) for key in changes}
    for key, value in changes.items():
        setattr(customer, key, value)
    add_audit(session, "customer", customer.id, "updated", {"before": before, "after": changes})
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("duplicate_customer", "Bu müşteri adı zaten kullanılıyor.", 409) from exc
    session.refresh(customer)
    return customer


@router.post("/customers/{customer_id}/archive", response_model=CustomerRead)
def archive_customer(customer_id: str, session: Session = Depends(get_session)):
    customer = get_customer(session, customer_id)
    if customer.status != RecordStatus.ACTIVE:
        raise ApiError("already_archived", "Müşteri zaten arşivlenmiş.", 409)
    customer.status = RecordStatus.ARCHIVED
    add_audit(session, "customer", customer.id, "archived")
    session.commit()
    session.refresh(customer)
    return customer


@router.post("/customers/{customer_id}/unarchive", response_model=CustomerRead)
def unarchive_customer(customer_id: str, session: Session = Depends(get_session)):
    customer = get_customer(session, customer_id)
    if customer.status != RecordStatus.ARCHIVED:
        raise ApiError("not_archived", "Müşteri arşivde değil.", 409)
    customer.status = RecordStatus.ACTIVE
    add_audit(session, "customer", customer.id, "unarchived")
    session.commit()
    session.refresh(customer)
    return customer


# --- Defter hesapları -------------------------------------------------------------------------------


def signed(movement: CustomerFinancialMovement) -> int:
    return movement.amount_kurus if movement.direction == INCREASE else -movement.amount_kurus


def _active_rows(
    session: Session,
    customer_id: str,
    *,
    as_of: date | None = None,
    project_id: str | None = None,
) -> list[CustomerFinancialMovement]:
    query = select(CustomerFinancialMovement).where(
        CustomerFinancialMovement.customer_id == customer_id,
        CustomerFinancialMovement.status == RecordStatus.ACTIVE,
    )
    if as_of is not None:
        query = query.where(CustomerFinancialMovement.movement_date <= as_of)
    if project_id is not None:
        query = query.where(CustomerFinancialMovement.project_id == project_id)
    return list(
        session.scalars(
            query.order_by(
                CustomerFinancialMovement.movement_date,
                CustomerFinancialMovement.created_at,
                CustomerFinancialMovement.id,
            )
        )
    )


def effective_rows(rows: list[CustomerFinancialMovement]) -> list[CustomerFinancialMovement]:
    """Ters satırlar ve hükümsüz kalan orijinaller çıkarılmış hareketler."""
    voided = {r.reversed_movement_id for r in rows if r.movement_type == "reversal"}
    return [r for r in rows if r.movement_type != "reversal" and r.id not in voided]


def ledger_balance(
    session: Session, customer_id: str, as_of: date | None = None, project_id: str | None = None
) -> int:
    # Ters satır zıt işaretli olduğundan tüm aktif satırların toplamı etkin bakiyeye eşittir.
    return sum(signed(r) for r in _active_rows(session, customer_id, as_of=as_of, project_id=project_id))


def allocation_totals(
    session: Session, customer_id: str, as_of: date | None = None
) -> tuple[dict[str, int], dict[str, int]]:
    """Aktif dağıtım toplamları: (plan -> tutar, tahsilat -> tutar)."""
    query = select(CustomerPaymentAllocation).where(
        CustomerPaymentAllocation.customer_id == customer_id,
        CustomerPaymentAllocation.status == RecordStatus.ACTIVE,
    )
    if as_of is not None:
        query = query.where(CustomerPaymentAllocation.allocation_date <= as_of)
    by_schedule: dict[str, int] = defaultdict(int)
    by_collection: dict[str, int] = defaultdict(int)
    for allocation in session.scalars(query):
        by_schedule[allocation.receivable_schedule_id] += allocation.amount_kurus
        by_collection[allocation.collection_id] += allocation.amount_kurus
    return dict(by_schedule), dict(by_collection)


def customer_position(session: Session, customer_id: str, as_of: date | None = None) -> dict:
    rows = _active_rows(session, customer_id, as_of=as_of)
    net = sum(signed(r) for r in rows)
    _, by_collection = allocation_totals(session, customer_id, as_of)
    unallocated = sum(
        r.amount_kurus - by_collection.get(r.id, 0)
        for r in effective_rows(rows)
        if r.movement_type == "collection"
    )
    return {
        "receivable_kurus": max(net, 0),
        "credit_kurus": max(-net, 0),
        "net_balance_kurus": net,
        "unallocated_collection_kurus": unallocated,
    }


@dataclass
class AgingItem:
    kind: str
    amount_kurus: int
    remaining_kurus: int
    due_date: date | None
    bucket: str
    days_overdue: int | None
    receivable_schedule_id: str | None = None
    project_id: str | None = None
    title: str | None = None
    source_ids: list[str] = field(default_factory=list)


def compute_receivables(session: Session, customer_id: str, as_of: date) -> dict:
    rows = _active_rows(session, customer_id, as_of=as_of)
    net = sum(signed(r) for r in rows)
    effective = effective_rows(rows)
    by_schedule, by_collection = allocation_totals(session, customer_id, as_of)
    collected = sum(r.amount_kurus for r in effective if r.movement_type == "collection")
    refunded = sum(r.amount_kurus for r in effective if r.movement_type == "refund")
    corrected = sum(
        r.amount_kurus if r.direction == DECREASE else -r.amount_kurus
        for r in effective
        if r.movement_type == "correction"
    )
    # Plana dağıtılmamış tahsilat havuzu yaşlandırmada en eski vadeden düşülür.
    pool = max(collected - sum(by_collection.values()) - refunded + corrected, 0)
    schedules = list(
        session.scalars(
            select(ReceivableSchedule).where(
                ReceivableSchedule.customer_id == customer_id,
                ReceivableSchedule.status == RecordStatus.ACTIVE,
            )
        )
    )
    schedules.sort(key=lambda s: (s.due_date or date.max, s.created_at, s.id))
    items: list[AgingItem] = []
    for schedule in schedules:
        remaining = max(schedule.amount_kurus - by_schedule.get(schedule.id, 0), 0)
        applied = min(pool, remaining)
        pool -= applied
        remaining -= applied
        if remaining <= 0:
            continue
        bucket, days = aging_bucket(schedule.due_date, as_of)
        items.append(
            AgingItem(
                kind="schedule",
                amount_kurus=schedule.amount_kurus,
                remaining_kurus=remaining,
                due_date=schedule.due_date,
                bucket=AGING_NAMES[bucket],
                days_overdue=days,
                receivable_schedule_id=schedule.id,
                project_id=schedule.project_id,
                title=schedule.title,
                source_ids=[schedule.id],
            )
        )
    scheduled_open = sum(i.remaining_kurus for i in items)
    receivable = max(net, 0)
    unscheduled = max(receivable - scheduled_open, 0)
    if unscheduled > 0:
        items.append(
            AgingItem(
                kind="unscheduled",
                amount_kurus=unscheduled,
                remaining_kurus=unscheduled,
                due_date=None,
                bucket="no_due_date",
                days_overdue=None,
                title="Plana bağlanmamış bakiye",
            )
        )
    position = customer_position(session, customer_id, as_of)
    return {
        "balance_kurus": net,
        "receivable_kurus": receivable,
        "credit_kurus": position["credit_kurus"],
        "unallocated_collection_kurus": position["unallocated_collection_kurus"],
        "items": items,
        "scheduled_open_kurus": scheduled_open,
        "unscheduled_kurus": unscheduled,
        "plan_excess_kurus": max(scheduled_open - receivable, 0),
    }


# --- Alacak planı -----------------------------------------------------------------------------------


class ScheduleCreate(BaseModel):
    customer_id: str
    project_id: str | None = None
    title: str = Field(min_length=2, max_length=180)
    amount_kurus: int = Field(gt=0)
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class ScheduleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    amount_kurus: int | None = Field(default=None, gt=0)
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_patch(self) -> ScheduleUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        for name in ("title", "amount_kurus"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} boş bırakılamaz.")
        return self


class ScheduleRead(OrmModel):
    id: str
    customer_id: str
    project_id: str | None
    title: str
    amount_kurus: int
    due_date: date | None
    note: str | None
    status: RecordStatus
    paid_kurus: int = 0
    remaining_kurus: int = 0
    payment_state: str = "open"


def _schedule_read(
    schedule: ReceivableSchedule, paid: int, as_of: date | None = None
) -> ScheduleRead:
    remaining = max(schedule.amount_kurus - paid, 0)
    if schedule.status != RecordStatus.ACTIVE:
        state = "cancelled"
    elif remaining == 0:
        state = "paid"
    elif as_of is not None and schedule.due_date is not None and schedule.due_date < as_of:
        state = "overdue"
    elif paid > 0:
        state = "partial"
    else:
        state = "open"
    read = ScheduleRead.model_validate(schedule)
    read.paid_kurus = paid
    read.remaining_kurus = remaining
    read.payment_state = state
    return read


def _check_project_for_customer(
    session: Session, customer: Customer, project_id: str | None
) -> Project | None:
    if project_id is None:
        return None
    project = session.get(Project, project_id)
    if project is None or project.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "Proje bulunamadı.", 404)
    if project.customer_id != customer.id:
        raise ApiError(
            "project_customer_mismatch", "Proje bu müşteriye ait değil.", 409,
            {"project_customer_id": project.customer_id},
        )
    return project


@router.post("/receivable-schedules", response_model=ScheduleRead, status_code=201)
def create_schedule(payload: ScheduleCreate, session: Session = Depends(get_session)):
    customer = require_open_customer(session, payload.customer_id)
    _check_project_for_customer(session, customer, payload.project_id)
    schedule = ReceivableSchedule(**payload.model_dump())
    session.add(schedule)
    session.flush()
    add_audit(
        session, "receivable_schedule", schedule.id, "created",
        {"customer_id": customer.id, "amount_kurus": schedule.amount_kurus},
    )
    session.commit()
    session.refresh(schedule)
    return _schedule_read(schedule, 0)


@router.get("/receivable-schedules", response_model=list[ScheduleRead])
def list_schedules(
    session: Session = Depends(get_session),
    customer_id: str | None = None,
    project_id: str | None = None,
    state: Literal["open", "partial", "paid", "overdue", "cancelled"] | None = None,
    as_of: date | None = None,
    include_cancelled: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(ReceivableSchedule)
    if customer_id:
        query = query.where(ReceivableSchedule.customer_id == customer_id)
    if project_id:
        query = query.where(ReceivableSchedule.project_id == project_id)
    if not include_cancelled and state != "cancelled":
        query = query.where(ReceivableSchedule.status == RecordStatus.ACTIVE)
    schedules = list(
        session.scalars(
            query.order_by(ReceivableSchedule.due_date.is_(None), ReceivableSchedule.due_date, ReceivableSchedule.id)
        )
    )
    paid_by_customer: dict[str, dict[str, int]] = {}
    result = []
    for schedule in schedules:
        if schedule.customer_id not in paid_by_customer:
            paid_by_customer[schedule.customer_id] = allocation_totals(
                session, schedule.customer_id
            )[0]
        read = _schedule_read(schedule, paid_by_customer[schedule.customer_id].get(schedule.id, 0), as_of)
        if state is None or read.payment_state == state:
            result.append(read)
    return result[offset : offset + limit]


def _get_schedule(session: Session, schedule_id: str) -> ReceivableSchedule:
    schedule = session.get(ReceivableSchedule, schedule_id)
    if schedule is None:
        raise ApiError("not_found", "Alacak planı bulunamadı.", 404)
    return schedule


@router.patch("/receivable-schedules/{schedule_id}", response_model=ScheduleRead)
def update_schedule(
    schedule_id: str, payload: ScheduleUpdate, session: Session = Depends(get_session)
):
    schedule = _get_schedule(session, schedule_id)
    if schedule.status != RecordStatus.ACTIVE:
        raise ApiError("schedule_cancelled", "İptal edilmiş alacak planı düzenlenemez.", 409)
    changes = payload.model_dump(exclude_unset=True)
    paid = allocation_totals(session, schedule.customer_id)[0].get(schedule.id, 0)
    if "amount_kurus" in changes and changes["amount_kurus"] < paid:
        raise ApiError(
            "amount_below_collected",
            "Plan tutarı bu plana bağlı tahsilat toplamının altına düşürülemez.",
            409,
            {"collected_kurus": paid},
        )
    before = {key: getattr(schedule, key) for key in changes}
    for key, value in changes.items():
        setattr(schedule, key, value)
    add_audit(session, "receivable_schedule", schedule.id, "updated", {"before": before, "after": changes})
    session.commit()
    session.refresh(schedule)
    return _schedule_read(schedule, paid)


@router.post("/receivable-schedules/{schedule_id}/cancel", response_model=ScheduleRead)
def cancel_schedule(schedule_id: str, session: Session = Depends(get_session)):
    schedule = _get_schedule(session, schedule_id)
    if schedule.status != RecordStatus.ACTIVE:
        raise ApiError("schedule_cancelled", "Alacak planı zaten iptal edilmiş.", 409)
    active = list(
        session.scalars(
            select(CustomerPaymentAllocation.id).where(
                CustomerPaymentAllocation.receivable_schedule_id == schedule.id,
                CustomerPaymentAllocation.status == RecordStatus.ACTIVE,
            )
        )
    )
    if active:
        raise ApiError(
            "schedule_has_allocations",
            "Aktif tahsilat dağıtımı olan plan önce dağıtımlar iptal edilmeden iptal edilemez.",
            409,
            {"allocation_ids": active},
        )
    schedule.status = RecordStatus.CANCELLED
    add_audit(session, "receivable_schedule", schedule.id, "cancelled")
    session.commit()
    session.refresh(schedule)
    return _schedule_read(schedule, 0)


# --- Defter hareketleri -----------------------------------------------------------------------------


class CustomerMovementCreate(BaseModel):
    customer_id: str
    project_id: str | None = None
    receivable_schedule_id: str | None = None
    change_order_id: str | None = None
    movement_date: date
    movement_type: MovementTypeName
    direction: Direction | None = None
    amount_kurus: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def validate_movement(self) -> CustomerMovementCreate:
        if self.movement_type == "reversal":
            raise ValueError("Ters kayıt yalnız reverse uç noktasıyla oluşturulur.")
        allowed = ALLOWED_DIRECTIONS[self.movement_type]
        if self.direction is None:
            if len(allowed) != 1:
                raise ValueError("Bu hareket türü için direction belirtilmelidir.")
            self.direction = next(iter(allowed))  # type: ignore[assignment]
        if self.direction not in allowed:
            raise ValueError("Bu hareket türü için geçersiz direction.")
        if self.change_order_id and self.movement_type != "accrual":
            raise ValueError("Ek iş yalnız tahakkuk hareketine bağlanabilir.")
        if self.receivable_schedule_id and self.movement_type != "collection":
            raise ValueError("Alacak planı yalnız tahsilat hareketine bağlanabilir.")
        return self


class CustomerMovementRead(OrmModel):
    id: str
    customer_id: str
    project_id: str | None
    receivable_schedule_id: str | None
    change_order_id: str | None
    movement_date: date
    movement_type: str
    direction: str
    amount_kurus: int
    note: str | None
    idempotency_key: str
    reversed_movement_id: str | None
    source: str
    status: RecordStatus
    is_voided: bool = False
    allocated_kurus: int | None = None  # yalnız tahsilatta
    unallocated_kurus: int | None = None


class ReverseRequest(BaseModel):
    # Verilmezse sunucunun iş tarihi (orijinalden önceyse orijinalin tarihi) kullanılır. İstemci her
    # zaman bugünün tarihini açıkça göndermelidir; geçmiş tarihli ekstreler geriye dönük değişmez.
    movement_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


def _movement_read(movement: CustomerFinancialMovement, voided: bool = False) -> CustomerMovementRead:
    read = CustomerMovementRead.model_validate(movement)
    read.is_voided = voided
    return read


def _voided_ids(session: Session, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    return set(
        session.scalars(
            select(CustomerFinancialMovement.reversed_movement_id).where(
                CustomerFinancialMovement.reversed_movement_id.in_(ids),
                CustomerFinancialMovement.status == RecordStatus.ACTIVE,
            )
        )
    )


def _same_request(existing: CustomerFinancialMovement, payload: CustomerMovementCreate) -> bool:
    return (
        existing.customer_id == payload.customer_id
        and existing.movement_type == payload.movement_type
        and existing.direction == payload.direction
        and existing.amount_kurus == payload.amount_kurus
        and existing.movement_date == payload.movement_date
        and existing.project_id == payload.project_id
        and existing.receivable_schedule_id == payload.receivable_schedule_id
        and existing.change_order_id == payload.change_order_id
    )


def _decorate(session: Session, reads: list[CustomerMovementRead]) -> list[CustomerMovementRead]:
    ids = [r.id for r in reads if r.movement_type == "collection"]
    if not ids:
        return reads
    sums = dict(
        session.execute(
            select(
                CustomerPaymentAllocation.collection_id,
                func.sum(CustomerPaymentAllocation.amount_kurus),
            )
            .where(
                CustomerPaymentAllocation.collection_id.in_(ids),
                CustomerPaymentAllocation.status == RecordStatus.ACTIVE,
            )
            .group_by(CustomerPaymentAllocation.collection_id)
        ).all()
    )
    for read in reads:
        if read.movement_type == "collection":
            read.allocated_kurus = int(sums.get(read.id, 0))
            read.unallocated_kurus = (
                0 if read.is_voided else read.amount_kurus - read.allocated_kurus
            )
    return reads


def _auto_allocate(
    session: Session, movement: CustomerFinancialMovement, schedule: ReceivableSchedule | None
) -> None:
    """Plana bağlı tahsilat planın kalanı kadar dağıtılır; fazlası dağıtılmamış (avans) kalır."""
    if schedule is None or movement.movement_type != "collection":
        return
    paid = allocation_totals(session, movement.customer_id)[0].get(schedule.id, 0)
    amount = min(movement.amount_kurus, max(schedule.amount_kurus - paid, 0))
    if amount > 0:
        session.add(
            CustomerPaymentAllocation(
                customer_id=movement.customer_id,
                collection_id=movement.id,
                receivable_schedule_id=schedule.id,
                amount_kurus=amount,
                allocation_date=movement.movement_date,
                idempotency_key=f"{movement.idempotency_key}:alloc",
            )
        )


@router.post("/customer-financial-movements", response_model=CustomerMovementRead, status_code=201)
def create_customer_movement(
    payload: CustomerMovementCreate, session: Session = Depends(get_session)
):
    existing = session.scalar(
        select(CustomerFinancialMovement).where(
            CustomerFinancialMovement.idempotency_key == payload.idempotency_key
        )
    )
    if existing is not None:
        if not _same_request(existing, payload):
            raise ApiError(
                "idempotency_conflict", "Bu anahtar farklı bir hareket için kullanılmış.", 409
            )
        return _decorate(
            session, [_movement_read(existing, existing.id in _voided_ids(session, [existing.id]))]
        )[0]

    customer = require_open_customer(session, payload.customer_id)
    _check_project_for_customer(session, customer, payload.project_id)
    rows = _active_rows(session, customer.id)

    if payload.change_order_id:
        order = session.get(ProjectChangeOrder, payload.change_order_id)
        if order is None or order.status != RecordStatus.ACTIVE:
            raise ApiError("not_found", "Ek iş bulunamadı.", 404)
        if payload.project_id != order.project_id:
            raise ApiError(
                "change_order_project_mismatch",
                "Ek iş tahakkuku ek işin projesiyle aynı projeye yazılmalıdır.",
                409,
            )
        if order.change_state != "approved":
            raise ApiError(
                "change_order_not_approved", "Yalnız onaylı ek iş tahakkuk edilebilir.", 409
            )

    schedule = None
    if payload.receivable_schedule_id:
        schedule = _get_schedule(session, payload.receivable_schedule_id)
        if schedule.customer_id != customer.id:
            raise ApiError("schedule_customer_mismatch", "Plan başka bir müşteriye ait.", 409)
        if schedule.status != RecordStatus.ACTIVE:
            raise ApiError("schedule_cancelled", "İptal edilmiş plana hareket bağlanamaz.", 409)
        if payload.project_id and schedule.project_id and payload.project_id != schedule.project_id:
            raise ApiError("schedule_project_mismatch", "Plan başka bir projeye ait.", 409)
    if payload.movement_type == "refund":
        collected = sum(
            r.amount_kurus if r.movement_type == "collection" else -r.amount_kurus
            for r in effective_rows(rows)
            if r.movement_type in {"collection", "refund"}
        )
        if payload.amount_kurus > collected:
            raise ApiError(
                "overrefund",
                "İade, net tahsilat toplamını aşıyor.",
                409,
                {"refundable_kurus": max(collected, 0)},
            )

    movement = CustomerFinancialMovement(
        **payload.model_dump(), source="manual"
    )
    session.add(movement)
    try:
        session.flush()
        _auto_allocate(session, movement, schedule)
        add_audit(
            session, "customer_movement", movement.id, "created",
            {
                "customer_id": customer.id,
                "movement_type": movement.movement_type,
                "amount_kurus": movement.amount_kurus,
            },
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            "idempotency_conflict", "Bu anahtar başka bir kayıtta kullanılmış.", 409
        ) from exc
    session.refresh(movement)
    return _decorate(session, [_movement_read(movement)])[0]


@router.get("/customer-financial-movements", response_model=list[CustomerMovementRead])
def list_customer_movements(
    session: Session = Depends(get_session),
    customer_id: str | None = None,
    project_id: str | None = None,
    movement_type: MovementTypeName | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if date_from and date_to and date_from > date_to:
        raise ApiError("invalid_range", "Başlangıç tarihi bitiş tarihinden sonra olamaz.", 422)
    query = select(CustomerFinancialMovement).where(
        CustomerFinancialMovement.status == RecordStatus.ACTIVE
    )
    if customer_id:
        query = query.where(CustomerFinancialMovement.customer_id == customer_id)
    if project_id:
        query = query.where(CustomerFinancialMovement.project_id == project_id)
    if movement_type:
        query = query.where(CustomerFinancialMovement.movement_type == movement_type)
    if date_from:
        query = query.where(CustomerFinancialMovement.movement_date >= date_from)
    if date_to:
        query = query.where(CustomerFinancialMovement.movement_date <= date_to)
    rows = list(
        session.scalars(
            query.order_by(
                CustomerFinancialMovement.movement_date.desc(),
                CustomerFinancialMovement.created_at.desc(),
                CustomerFinancialMovement.id,
            )
            .limit(limit)
            .offset(offset)
        )
    )
    voided = _voided_ids(session, [r.id for r in rows])
    return _decorate(session, [_movement_read(r, r.id in voided) for r in rows])


def _cancel_allocations_of(
    session: Session, collection: CustomerFinancialMovement, reason: str
) -> list[str]:
    cancelled = []
    for allocation in session.scalars(
        select(CustomerPaymentAllocation).where(
            CustomerPaymentAllocation.collection_id == collection.id,
            CustomerPaymentAllocation.status == RecordStatus.ACTIVE,
        )
    ):
        allocation.status = RecordStatus.CANCELLED
        allocation.cancelled_at = datetime.now(UTC)
        allocation.cancel_reason = reason
        add_audit(
            session, "customer_payment_allocation", allocation.id, "cancelled",
            {"reason": reason, "collection_id": collection.id},
        )
        cancelled.append(allocation.id)
    return cancelled


@router.post("/customer-financial-movements/{movement_id}/reverse", response_model=CustomerMovementRead, status_code=201)
def reverse_customer_movement(
    movement_id: str,
    payload: ReverseRequest | None = None,
    session: Session = Depends(get_session),
):
    payload = payload or ReverseRequest()
    original = session.get(CustomerFinancialMovement, movement_id)
    if original is None or original.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "Hareket bulunamadı.", 404)
    if original.movement_type == "reversal":
        raise ApiError("cannot_reverse_reversal", "Ters kayıt tekrar terslenemez.", 409)
    if session.scalar(
        select(CustomerFinancialMovement.id).where(
            CustomerFinancialMovement.reversed_movement_id == original.id
        )
    ):
        raise ApiError("already_reversed", "Bu hareket zaten terslenmiş.", 409)

    if payload.movement_date is not None and payload.movement_date < original.movement_date:
        raise ApiError(
            "invalid_reversal_date",
            "Ters kayıt tarihi orijinal hareket tarihinden önce olamaz.",
            422,
            {"original_date": original.movement_date},
        )
    reversal_date = payload.movement_date or max(clock.business_today(), original.movement_date)
    reversal = CustomerFinancialMovement(
        customer_id=original.customer_id,
        project_id=original.project_id,
        receivable_schedule_id=original.receivable_schedule_id,
        change_order_id=original.change_order_id,
        movement_date=reversal_date,
        movement_type="reversal",
        direction=DECREASE if original.direction == INCREASE else INCREASE,
        amount_kurus=original.amount_kurus,
        note=payload.note or f"Ters kayıt: {original.id}",
        idempotency_key=payload.idempotency_key or f"reverse:{original.id}",
        reversed_movement_id=original.id,
        source="system",
    )
    session.add(reversal)
    try:
        session.flush()
        cancelled = _cancel_allocations_of(session, original, "Tahsilat ters kaydı")
        add_audit(
            session, "customer_movement", original.id, "reversed",
            {"reversal_id": reversal.id, "cancelled_allocation_ids": cancelled},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("already_reversed", "Bu hareket zaten terslenmiş.", 409) from exc
    session.refresh(reversal)
    return _movement_read(reversal)


# --- Ekstre ve yaşlandırma --------------------------------------------------------------------------


@router.get("/customers/{customer_id}/statement")
def customer_statement(
    customer_id: str,
    session: Session = Depends(get_session),
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: str | None = None,
):
    customer = get_customer(session, customer_id)
    if date_from and date_to and date_from > date_to:
        raise ApiError("invalid_range", "Başlangıç tarihi bitiş tarihinden sonra olamaz.", 422)
    rows = _active_rows(session, customer.id, as_of=date_to, project_id=project_id)
    voided = {r.reversed_movement_id for r in rows if r.movement_type == "reversal"}
    opening = sum(signed(r) for r in rows if date_from and r.movement_date < date_from)
    running = opening
    lines = []
    total_in = total_out = 0
    for row in rows:
        if date_from and row.movement_date < date_from:
            continue
        amount = signed(row)
        running += amount
        total_in += max(amount, 0)
        total_out += max(-amount, 0)
        lines.append(
            {
                "movement_id": row.id,
                "movement_date": row.movement_date,
                "movement_type": row.movement_type,
                "direction": row.direction,
                "increase_kurus": max(amount, 0),
                "decrease_kurus": max(-amount, 0),
                "balance_kurus": running,
                "project_id": row.project_id,
                "receivable_schedule_id": row.receivable_schedule_id,
                "change_order_id": row.change_order_id,
                "reversed_movement_id": row.reversed_movement_id,
                "is_voided": row.id in voided,
                "note": row.note,
            }
        )
    return {
        "customer_id": customer.id,
        "customer_name": customer.name,
        "project_id": project_id,
        "date_from": date_from,
        "date_to": date_to,
        "opening_balance_kurus": opening,
        "total_increase_kurus": total_in,
        "total_decrease_kurus": total_out,
        "closing_balance_kurus": running,
        "closing_receivable_kurus": max(running, 0),
        "closing_credit_kurus": max(-running, 0),
        "rows": lines,
    }


@router.get("/customers/{customer_id}/aging")
def customer_aging(
    customer_id: str, session: Session = Depends(get_session), as_of: date | None = None
):
    customer = get_customer(session, customer_id)
    day = as_of or clock.business_today()
    result = compute_receivables(session, customer.id, day)
    buckets = {name: [0, 0] for name in AGING_NAMES.values()}
    for item in result["items"]:
        buckets[item.bucket][0] += item.remaining_kurus
        buckets[item.bucket][1] += 1
    overdue = sum(v[0] for k, v in buckets.items() if k in OVERDUE_NAMES)
    return {
        "customer_id": customer.id,
        "as_of": day,
        "balance_kurus": result["balance_kurus"],
        "net_balance_kurus": result["balance_kurus"],
        "receivable_kurus": result["receivable_kurus"],
        "open_receivable_kurus": sum(v[0] for v in buckets.values()),
        "advance_kurus": result["credit_kurus"],  # gecikmiş alacaktan ayrı gösterilir
        "unallocated_collection_kurus": result["unallocated_collection_kurus"],
        "overdue_kurus": overdue,
        "unscheduled_kurus": result["unscheduled_kurus"],
        "plan_excess_kurus": result["plan_excess_kurus"],
        "credit_kurus": result["credit_kurus"],
        "buckets": [
            {"bucket": key, "amount_kurus": v[0], "count": v[1]} for key, v in buckets.items()
        ],
        "items": [
            {
                "kind": i.kind,
                "receivable_schedule_id": i.receivable_schedule_id,
                "project_id": i.project_id,
                "title": i.title,
                "amount_kurus": i.amount_kurus,
                "remaining_kurus": i.remaining_kurus,
                "due_date": i.due_date,
                "bucket": i.bucket,
                "days_overdue": i.days_overdue,
            }
            for i in result["items"]
        ],
    }


# --- Tahsilat dağıtımı ------------------------------------------------------------------------------


class AllocationCreate(BaseModel):
    collection_id: str
    receivable_schedule_id: str
    amount_kurus: int = Field(gt=0)
    allocation_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)


class AllocationCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class AllocationRead(OrmModel):
    id: str
    customer_id: str
    collection_id: str
    receivable_schedule_id: str
    amount_kurus: int
    allocation_date: date
    note: str | None
    idempotency_key: str
    status: RecordStatus
    cancelled_at: datetime | None
    cancel_reason: str | None


@router.post("/customer-payment-allocations", response_model=AllocationRead, status_code=201)
def create_allocation(payload: AllocationCreate, session: Session = Depends(get_session)):
    existing = session.scalar(
        select(CustomerPaymentAllocation).where(
            CustomerPaymentAllocation.idempotency_key == payload.idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.collection_id != payload.collection_id
            or existing.receivable_schedule_id != payload.receivable_schedule_id
            or existing.amount_kurus != payload.amount_kurus
        ):
            raise ApiError(
                "idempotency_conflict", "Bu anahtar farklı bir dağıtım için kullanılmış.", 409
            )
        return existing

    collection = session.get(CustomerFinancialMovement, payload.collection_id)
    if (
        collection is None
        or collection.status != RecordStatus.ACTIVE
        or collection.movement_type != "collection"
    ):
        raise ApiError("not_found", "Tahsilat bulunamadı.", 404)
    if _voided_ids(session, [collection.id]):
        raise ApiError("collection_reversed", "Terslenmiş tahsilat dağıtılamaz.", 409)
    customer = require_open_customer(session, collection.customer_id)
    schedule = _get_schedule(session, payload.receivable_schedule_id)
    if schedule.customer_id != customer.id:
        raise ApiError("schedule_customer_mismatch", "Plan başka bir müşteriye ait.", 409)
    if schedule.status != RecordStatus.ACTIVE:
        raise ApiError("schedule_cancelled", "İptal edilmiş plana dağıtım yapılamaz.", 409)

    by_schedule, by_collection = allocation_totals(session, customer.id)
    unallocated = collection.amount_kurus - by_collection.get(collection.id, 0)
    if payload.amount_kurus > unallocated:
        raise ApiError(
            "allocation_exceeds_collection",
            "Dağıtım tahsilatın dağıtılmamış tutarını aşıyor.",
            409,
            {"unallocated_kurus": unallocated},
        )
    room = schedule.amount_kurus - by_schedule.get(schedule.id, 0)
    if payload.amount_kurus > room:
        raise ApiError(
            "allocation_exceeds_schedule",
            "Dağıtım planın kalan tutarını aşıyor.",
            409,
            {"remaining_kurus": max(room, 0)},
        )
    day = payload.allocation_date or max(clock.business_today(), collection.movement_date)
    if day < collection.movement_date:
        raise ApiError(
            "invalid_allocation_date",
            "Dağıtım tarihi tahsilat tarihinden önce olamaz.",
            422,
            {"collection_date": collection.movement_date},
        )
    allocation = CustomerPaymentAllocation(
        customer_id=customer.id,
        collection_id=collection.id,
        receivable_schedule_id=schedule.id,
        amount_kurus=payload.amount_kurus,
        allocation_date=day,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
    )
    session.add(allocation)
    try:
        session.flush()
        add_audit(
            session, "customer_payment_allocation", allocation.id, "created",
            {
                "collection_id": collection.id,
                "receivable_schedule_id": schedule.id,
                "amount_kurus": allocation.amount_kurus,
            },
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            "idempotency_conflict", "Bu anahtar başka bir kayıtta kullanılmış.", 409
        ) from exc
    session.refresh(allocation)
    return allocation


@router.get("/customer-payment-allocations", response_model=list[AllocationRead])
def list_allocations(
    session: Session = Depends(get_session),
    customer_id: str | None = None,
    collection_id: str | None = None,
    receivable_schedule_id: str | None = None,
    include_cancelled: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(CustomerPaymentAllocation)
    if customer_id:
        query = query.where(CustomerPaymentAllocation.customer_id == customer_id)
    if collection_id:
        query = query.where(CustomerPaymentAllocation.collection_id == collection_id)
    if receivable_schedule_id:
        query = query.where(
            CustomerPaymentAllocation.receivable_schedule_id == receivable_schedule_id
        )
    if not include_cancelled:
        query = query.where(CustomerPaymentAllocation.status == RecordStatus.ACTIVE)
    return session.scalars(
        query.order_by(CustomerPaymentAllocation.allocation_date, CustomerPaymentAllocation.id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/customer-payment-allocations/{allocation_id}/cancel", response_model=AllocationRead)
def cancel_allocation(
    allocation_id: str,
    payload: AllocationCancel | None = None,
    session: Session = Depends(get_session),
):
    allocation = session.get(CustomerPaymentAllocation, allocation_id)
    if allocation is None:
        raise ApiError("not_found", "Dağıtım bulunamadı.", 404)
    if allocation.status != RecordStatus.ACTIVE:
        raise ApiError("allocation_cancelled", "Dağıtım zaten iptal edilmiş.", 409)
    reason = payload.reason if payload else None
    allocation.status = RecordStatus.CANCELLED
    allocation.cancelled_at = datetime.now(UTC)
    allocation.cancel_reason = reason
    add_audit(
        session, "customer_payment_allocation", allocation.id, "cancelled", {"reason": reason}
    )
    session.commit()
    session.refresh(allocation)
    return allocation

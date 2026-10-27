from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_sidecar_token
from .database import get_session
from .models import Employee, EmployeeWageRate, RecordStatus
from .schemas import (
    EmployeeCreate,
    EmployeeRead,
    EmployeeUpdate,
    WageRateCreate,
    WageRateRead,
)
from .wages import add_wage_rate, initial_rate_start, load_rate_book, sync_employee_rate_cache

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])


def get_employee(session: Session, employee_id: str, *, allow_archived: bool = True) -> Employee:
    employee = session.get(Employee, employee_id)
    if employee is None or employee.status == RecordStatus.CANCELLED:
        raise ApiError("not_found", "Personel bulunamadı.", 404)
    if not allow_archived and employee.status != RecordStatus.ACTIVE:
        raise ApiError("employee_archived", "Personel arşivlenmiş.", 409)
    return employee


def serialize_employees(
    session: Session, employees: list[Employee], today: date | None = None
) -> list[EmployeeRead]:
    """Güncel ücret alanlarını bugün geçerli ücret kaydından türetir (tek sorgu)."""
    day = today or date.today()
    book = load_rate_book(session, [employee.id for employee in employees])
    output: list[EmployeeRead] = []
    for employee in employees:
        read = EmployeeRead.model_validate(employee)
        rate = book.at(employee.id, day)
        if rate is not None:
            read.wage_type = rate.wage_type
            read.current_rate_kurus = rate.rate_kurus
            read.daily_rate_kurus = rate.rate_kurus if rate.wage_type == "daily" else None
        output.append(read)
    return output


def serialize_employee(session: Session, employee: Employee) -> EmployeeRead:
    return serialize_employees(session, [employee])[0]


@router.post("/employees", response_model=EmployeeRead, status_code=201)
def create_employee(payload: EmployeeCreate, session: Session = Depends(get_session)):
    data = payload.model_dump(
        exclude={"daily_rate_kurus", "wage_type", "current_rate_kurus", "rate_effective_from"}
    )
    employee = Employee(**data, wage_type=payload.wage_type or "daily")
    session.add(employee)
    session.flush()
    add_audit(session, "employee", employee.id, "created")
    if payload.current_rate_kurus is not None:
        rate = add_wage_rate(
            session,
            employee,
            WageRateCreate(
                effective_from=initial_rate_start(employee, payload.rate_effective_from),
                wage_type=payload.wage_type or "daily",
                rate_kurus=payload.current_rate_kurus,
                reason="Personel kartı açılışı",
            ),
            date.today(),
        )
        employee.current_rate_kurus = rate.rate_kurus
        sync_employee_rate_cache(employee, load_rate_book(session, [employee.id]), date.today())
    session.commit()
    session.refresh(employee)
    return serialize_employee(session, employee)


@router.get("/employees", response_model=list[EmployeeRead])
def list_employees(
    session: Session = Depends(get_session),
    employment_state: str | None = Query(default=None, pattern="^(active|inactive|left)$"),
    include_archived: bool = False,
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(Employee)
    if not include_archived:
        query = query.where(Employee.status == RecordStatus.ACTIVE)
    else:
        query = query.where(Employee.status != RecordStatus.CANCELLED)
    if employment_state:
        query = query.where(Employee.employment_state == employment_state)
    if q:
        escaped = q.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(func.lower(Employee.name).like(f"%{escaped}%", escape="\\"))
    employees = session.scalars(
        query.order_by(Employee.name, Employee.id).limit(limit).offset(offset)
    ).all()
    return serialize_employees(session, list(employees))


@router.patch("/employees/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: str, payload: EmployeeUpdate, session: Session = Depends(get_session)
):
    employee = get_employee(session, employee_id, allow_archived=False)
    changes = payload.model_dump(exclude_unset=True)
    start = changes.get("employment_start_date", employee.employment_start_date)
    end = changes.get("employment_end_date", employee.employment_end_date)
    if start and end and end < start:
        raise ApiError("invalid_range", "İşten ayrılış tarihi başlangıçtan önce olamaz.", 422)
    before = {key: getattr(employee, key) for key in changes}
    for key, value in changes.items():
        setattr(employee, key, value)
    add_audit(session, "employee", employee.id, "updated", {"before": before, "after": changes})
    session.commit()
    session.refresh(employee)
    return serialize_employee(session, employee)


@router.post("/employees/{employee_id}/archive", response_model=EmployeeRead)
def archive_employee(employee_id: str, session: Session = Depends(get_session)):
    employee = get_employee(session, employee_id)
    if employee.status != RecordStatus.ARCHIVED:
        employee.status = RecordStatus.ARCHIVED
        if employee.employment_state == "active":
            employee.employment_state = "inactive"
        add_audit(session, "employee", employee.id, "archived")
        session.commit()
        session.refresh(employee)
    return serialize_employee(session, employee)


@router.get("/employees/{employee_id}/wage-rates", response_model=list[WageRateRead])
def list_wage_rates(
    employee_id: str,
    session: Session = Depends(get_session),
    include_cancelled: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    get_employee(session, employee_id)
    query = select(EmployeeWageRate).where(EmployeeWageRate.employee_id == employee_id)
    if not include_cancelled:
        query = query.where(EmployeeWageRate.status == RecordStatus.ACTIVE)
    return session.scalars(
        query.order_by(EmployeeWageRate.effective_from.desc(), EmployeeWageRate.id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/employees/{employee_id}/wage-rates", response_model=WageRateRead, status_code=201)
def create_wage_rate(
    employee_id: str, payload: WageRateCreate, session: Session = Depends(get_session)
):
    employee = get_employee(session, employee_id, allow_archived=False)
    rate = add_wage_rate(session, employee, payload, date.today())
    session.commit()
    session.refresh(rate)
    return rate


@router.post(
    "/employees/{employee_id}/wage-rates/{rate_id}/cancel", response_model=WageRateRead
)
def cancel_wage_rate(employee_id: str, rate_id: str, session: Session = Depends(get_session)):
    employee = get_employee(session, employee_id)
    rate = session.get(EmployeeWageRate, rate_id)
    if rate is None or rate.employee_id != employee.id or rate.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "Ücret kaydı bulunamadı.", 404)
    rate.status = RecordStatus.CANCELLED
    add_audit(session, "employee_wage_rate", rate.id, "cancelled")
    session.flush()
    sync_employee_rate_cache(employee, load_rate_book(session, [employee.id]), date.today())
    session.commit()
    session.refresh(rate)
    return rate

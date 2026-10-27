"""Personel ücret geçmişi: tarihe göre geçerli ücret araması ve çakışmasız dönem yönetimi."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import ApiError, add_audit
from .models import Employee, EmployeeWageRate, RecordStatus
from .schemas import DEFAULT_RATE_START, WageRateCreate


class RateBook:
    """Birden fazla personelin ücret geçmişini tek sorguyla yükleyip O(log n) arama sağlar."""

    def __init__(self, rates: Iterable[EmployeeWageRate]):
        grouped: dict[str, list[EmployeeWageRate]] = defaultdict(list)
        for rate in rates:
            if rate.status == RecordStatus.ACTIVE:
                grouped[rate.employee_id].append(rate)
        self._rates: dict[str, list[EmployeeWageRate]] = {}
        self._starts: dict[str, list[date]] = {}
        for employee_id, items in grouped.items():
            items.sort(key=lambda item: (item.effective_from, item.id))
            self._rates[employee_id] = items
            self._starts[employee_id] = [item.effective_from for item in items]

    def at(self, employee_id: str, day: date) -> EmployeeWageRate | None:
        starts = self._starts.get(employee_id)
        if not starts:
            return None
        index = bisect_right(starts, day) - 1
        # Dönemler çakışmadığı için en yakın başlangıç adayı yeterlidir.
        if index < 0:
            return None
        rate = self._rates[employee_id][index]
        if rate.effective_to is not None and rate.effective_to < day:
            return None
        return rate

    def for_employee(self, employee_id: str) -> list[EmployeeWageRate]:
        return list(self._rates.get(employee_id, []))


def load_rate_book(session: Session, employee_ids: Iterable[str] | None = None) -> RateBook:
    query = select(EmployeeWageRate).where(EmployeeWageRate.status == RecordStatus.ACTIVE)
    if employee_ids is not None:
        ids = list(set(employee_ids))
        if not ids:
            return RateBook([])
        query = query.where(EmployeeWageRate.employee_id.in_(ids))
    return RateBook(session.scalars(query).all())


def sync_employee_rate_cache(employee: Employee, book: RateBook, today: date) -> None:
    """Personel kartındaki güncel ücret alanlarını bugün geçerli kayıttan yeniler."""
    rate = book.at(employee.id, today)
    if rate is None:
        return
    employee.wage_type = rate.wage_type
    employee.current_rate_kurus = rate.rate_kurus
    employee.daily_rate_kurus = rate.rate_kurus if rate.wage_type == "daily" else None


def add_wage_rate(
    session: Session, employee: Employee, payload: WageRateCreate, today: date
) -> EmployeeWageRate:
    existing = session.scalars(
        select(EmployeeWageRate)
        .where(
            EmployeeWageRate.employee_id == employee.id,
            EmployeeWageRate.status == RecordStatus.ACTIVE,
        )
        .order_by(EmployeeWageRate.effective_from)
    ).all()
    new_end = payload.effective_to or date.max
    overlapping = [
        rate
        for rate in existing
        if rate.effective_from <= new_end and payload.effective_from <= (rate.effective_to or date.max)
    ]
    closable = (
        len(overlapping) == 1
        and overlapping[0].effective_to is None
        and overlapping[0].effective_from < payload.effective_from
        and payload.effective_to is None
    )
    if overlapping and not closable:
        raise ApiError(
            "wage_rate_overlap",
            "Ücret dönemi mevcut bir ücret dönemiyle çakışıyor.",
            409,
            [
                {
                    "id": rate.id,
                    "effective_from": rate.effective_from.isoformat(),
                    "effective_to": rate.effective_to.isoformat() if rate.effective_to else None,
                }
                for rate in overlapping
            ],
        )
    if closable:
        previous = overlapping[0]
        closing_day = payload.effective_from - timedelta(days=1)
        previous.effective_to = closing_day
        add_audit(
            session,
            "employee_wage_rate",
            previous.id,
            "closed",
            {"before": {"effective_to": None}, "after": {"effective_to": closing_day}},
        )
    rate = EmployeeWageRate(employee_id=employee.id, **payload.model_dump())
    session.add(rate)
    session.flush()
    add_audit(
        session,
        "employee_wage_rate",
        rate.id,
        "created",
        {"employee_id": employee.id, **payload.model_dump()},
    )
    session.flush()
    sync_employee_rate_cache(employee, load_rate_book(session, [employee.id]), today)
    return rate


def initial_rate_start(employee: Employee, explicit: date | None) -> date:
    return explicit or employee.employment_start_date or DEFAULT_RATE_START

"""Kesinleşmiş (finalized/closed) maaş dönemlerine ait tarihleri sessiz değişikliklere karşı korur."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import ApiError
from .models import PayrollPeriod, RecordStatus

LOCKED_STATES = ("finalized", "closed")


def locked_periods(session: Session, start: date, end: date) -> list[PayrollPeriod]:
    return list(
        session.scalars(
            select(PayrollPeriod).where(
                PayrollPeriod.status == RecordStatus.ACTIVE,
                PayrollPeriod.state.in_(LOCKED_STATES),
                PayrollPeriod.period_start <= end,
                PayrollPeriod.period_end >= start,
            )
        )
    )


def assert_range_unlocked(session: Session, start: date, end: date, what: str) -> None:
    hit = locked_periods(session, start, end)
    if hit:
        raise ApiError(
            "period_locked",
            f"{what} kesinleşmiş bir maaş dönemini etkiliyor; düzeltme hareketi kullanın.",
            409,
            [{"payroll_period_id": p.id, "title": p.title, "state": p.state} for p in hit],
        )


def assert_dates_unlocked(session: Session, days: list[date], what: str) -> None:
    for day in sorted(set(days)):
        assert_range_unlocked(session, day, day, what)

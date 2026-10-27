"""Kesinleşmiş maaş dönemlerine ait tarihleri değişikliklere karşı korur."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session


def assert_dates_unlocked(session: Session, days: list[date], what: str) -> None:
    """Maaş dönemi tabloları eklenene kadar kilitlenecek dönem yoktur."""
    return

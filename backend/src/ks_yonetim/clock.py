"""İş tarihi kaynağı. Sistem saati yalnız burada okunur; testler `business_today`'i sabitler."""

from __future__ import annotations

from datetime import date


def business_today() -> date:
    return date.today()

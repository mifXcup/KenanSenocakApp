"""İşçilik maliyeti: tarihte geçerli ücretten deterministik (Decimal, tek yuvarlama) hesap."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AppSetting

# Elle (puantaj ekranı / Excel) girilebilen durumlar.
WORK_STATUSES = (
    "worked",
    "half_day",
    "overtime",
    "paid_leave",
    "unpaid_leave",
    "absent",
    "public_holiday",
    "weekly_rest",
)
# Yalnız izin talebi onayıyla üretilen durumlar (izin hak defteriyle tutarlı kalsın diye).
LEAVE_MANAGED_STATUSES = frozenset({"annual_leave", "sick_leave", "excused_leave"})
ALL_STATUSES = WORK_STATUSES + tuple(sorted(LEAVE_MANAGED_STATUSES))
PAID_STATUSES = frozenset(
    {"worked", "half_day", "overtime", "paid_leave", "annual_leave", "public_holiday"}
)
# Ücretsiz: raporlu (işveren ödemez) ve mazeret izni de ücretsiz sayılır.
UNPAID_STATUSES = frozenset({"unpaid_leave", "absent", "sick_leave", "excused_leave"})
# Ücreti etkilemeyen takvim durumu: aylıkta kesinti yok, günlük/saatlikte ödeme yok.
NEUTRAL_STATUSES = frozenset({"weekly_rest"})
HOUR_QUANT = Decimal("0.01")

SETTING_DEFAULTS = {"overtime_multiplier_percent": 150, "standard_day_hours": 8}


@dataclass(frozen=True)
class LaborSettings:
    overtime_multiplier_percent: int = 150
    standard_day_hours: int = 8

    def as_dict(self) -> dict[str, int]:
        return {
            "overtime_multiplier_percent": self.overtime_multiplier_percent,
            "standard_day_hours": self.standard_day_hours,
        }


def load_settings(session: Session) -> LaborSettings:
    stored = {
        key: int(value)
        for key, value in session.execute(select(AppSetting.key, AppSetting.value)).all()
        if key in SETTING_DEFAULTS
    }
    return LaborSettings(**{**SETTING_DEFAULTS, **stored})


class HoursError(ValueError):
    pass


def normalize_hours(
    status: str,
    normal_hours: Decimal | None,
    overtime_hours: Decimal | None,
    settings: LaborSettings,
) -> tuple[Decimal, Decimal]:
    """Duruma göre varsayılan saatleri uygular ve tutarsız girişleri reddeder."""
    standard = Decimal(settings.standard_day_hours)
    overtime = Decimal(overtime_hours or 0)
    if status in UNPAID_STATUSES or status in NEUTRAL_STATUSES:
        if (normal_hours or 0) > 0 or overtime > 0:
            raise HoursError("Ücretsiz izin, devamsızlık ve haftalık izin kaydında saat girilemez.")
        return Decimal("0.00"), Decimal("0.00")
    if status == "overtime":
        if overtime <= 0:
            raise HoursError("Fazla mesai kaydında fazla mesai saati sıfırdan büyük olmalıdır.")
        normal = standard if normal_hours is None else Decimal(normal_hours)
    else:
        if overtime > 0:
            raise HoursError("Fazla mesai saati yalnız 'overtime' durumunda girilebilir.")
        if normal_hours is None:
            normal = standard / 2 if status == "half_day" else standard
        else:
            normal = Decimal(normal_hours)
    if normal <= 0:
        raise HoursError("Normal çalışma saati sıfırdan büyük olmalıdır.")
    if status == "half_day" and normal > standard:
        raise HoursError("Yarım gün saati günlük normal süreyi aşamaz.")
    if normal + overtime > 24:
        raise HoursError("Bir günde toplam saat 24'ü aşamaz.")
    return normal.quantize(HOUR_QUANT), overtime.quantize(HOUR_QUANT)


def days_in_month(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def daily_equivalent(rate_kurus: int, wage_type: str, day: date, settings: LaborSettings) -> Decimal:
    """Bir tam gün normal çalışmanın değeri (yuvarlanmamış)."""
    rate = Decimal(rate_kurus)
    if wage_type == "daily":
        return rate
    if wage_type == "hourly":
        return rate * settings.standard_day_hours
    return rate / days_in_month(day)  # monthly: takvim günü başına


def hourly_equivalent(rate_kurus: int, wage_type: str, day: date, settings: LaborSettings) -> Decimal:
    if wage_type == "hourly":
        return Decimal(rate_kurus)
    return daily_equivalent(rate_kurus, wage_type, day, settings) / settings.standard_day_hours


def normal_pay(
    rate_kurus: int, wage_type: str, day: date, normal_hours: Decimal, settings: LaborSettings
) -> Decimal:
    return hourly_equivalent(rate_kurus, wage_type, day, settings) * normal_hours


def overtime_pay(
    rate_kurus: int,
    wage_type: str,
    day: date,
    overtime_hours: Decimal,
    settings: LaborSettings,
    multiplier_percent: int | None = None,
) -> Decimal:
    multiplier = Decimal(multiplier_percent or settings.overtime_multiplier_percent) / 100
    return hourly_equivalent(rate_kurus, wage_type, day, settings) * overtime_hours * multiplier


def to_kurus(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def work_log_amount(
    status: str,
    rate_kurus: int,
    wage_type: str,
    day: date,
    normal_hours: Decimal,
    overtime_hours: Decimal,
    settings: LaborSettings,
) -> int:
    if status in UNPAID_STATUSES:
        return 0
    total = normal_pay(rate_kurus, wage_type, day, normal_hours, settings)
    if overtime_hours > 0:
        total += overtime_pay(rate_kurus, wage_type, day, overtime_hours, settings)
    return to_kurus(total)

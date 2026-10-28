"""Yerel, açıklanabilir tahmin modelleri.

Hiçbir model dış ağa, bulut servisine veya üçüncü taraf yapay zekâya veri göndermez; yalnızca yerel
SQLite verisi üzerinde saf Python istatistikleri (medyan, doğrusal regresyon, sapma) çalışır.
Aynı veri ve aynı `as_of` tarihi her zaman aynı sonucu üretir. Tahminler hiçbir zaman otomatik
finansal hareket oluşturmaz.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from statistics import median, pstdev
from typing import Literal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_sidecar_token
from .database import get_session
from .finance import classify, compute_positions, load_effective
from .models import (
    Employee,
    EmployeeFinancialMovement,
    Material,
    MlPrediction,
    MlRun,
    PayrollEntry,
    PayrollPeriod,
    Project,
    ProjectExpense,
    Purchase,
    RecordStatus,
    Supplier,
    WorkLog,
)
from .schemas import MLInsights, MLStatus, PriceAnomaly, ProjectRisk, ReorderForecast

router = APIRouter(prefix="/api/v1/analytics/ml", dependencies=[Depends(require_sidecar_token)])

MIN_PRICE_SAMPLES = 5
MIN_REORDER_SAMPLES = 4
MIN_PROJECT_EVENTS = 4
MIN_SUPPLIER_COUNT = 2
MIN_SUPPLIER_RECORDS = 2
MIN_CLOSED_PAYROLL_PERIODS = 3
MAX_QUANTITY_RATIO = 3.0
MIN_PRICE_GAP_PERCENT = 2.0
MODEL_VERSION = "1.0"
MODEL_NAMES = (
    "price_anomaly",
    "reorder",
    "project_budget_risk",
    "supplier_price_comparison",
    "payroll_load",
    "employee_debt_risk",
)
ModelName = Literal[
    "price_anomaly",
    "reorder",
    "project_budget_risk",
    "supplier_price_comparison",
    "payroll_load",
    "employee_debt_risk",
]
OPENING_PREFIX = "opening:"
OPENING_MATERIAL = "Açılış Bakiyesi"


def usable_purchases():
    """Açılış bakiyesi aktarımları, iptal edilenler ve henüz teslim alınmamış (planlı/siparişli)
    satın almalar model verisine girmez."""
    return (
        Purchase.status == RecordStatus.ACTIVE,
        Purchase.lifecycle_state.in_(("received", "partially_received")),
        ~Purchase.idempotency_key.like(f"{OPENING_PREFIX}%"),
        Material.name != OPENING_MATERIAL,
    )


def linear_fit(points: list[tuple[float, float]]) -> tuple[float, float]:
    count = len(points)
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    slope = (
        sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator if denominator else 0.0
    )
    return mean_y - slope * mean_x, slope


def unit_price(purchase: Purchase) -> int:
    if purchase.unit_price_kurus is not None:
        return purchase.unit_price_kurus
    return int(Decimal(purchase.total_kurus) / purchase.quantity)


# --- A. Malzeme fiyat anomalisi ------------------------------------------------------------------


class PriceAnomalyOut(PriceAnomaly):
    explanation: str = ""
    first_date: date | None = None


def price_insights(session: Session) -> tuple[list[PriceAnomalyOut], int]:
    series: dict[tuple[str, str], list[tuple[date, int]]] = defaultdict(list)
    names: dict[str, str] = {}
    unit_labels: dict[tuple[str, str], str] = {}
    rows = session.execute(
        select(Purchase, Material.name)
        .join(Material, Material.id == Purchase.material_id)
        .where(
            *usable_purchases(),
            Purchase.quantity.is_not(None),
            Purchase.quantity > 0,
            Purchase.unit.is_not(None),
        )
        .order_by(Purchase.purchase_date, Purchase.created_at, Purchase.id)
    )
    for purchase, material_name in rows:
        key = (purchase.material_id, purchase.unit.strip().casefold())  # birimler karışmaz
        series[key].append((purchase.purchase_date, unit_price(purchase)))
        unit_labels.setdefault(key, purchase.unit)
        names[purchase.material_id] = material_name

    ready_count = sum(1 for values in series.values() if len(values) >= MIN_PRICE_SAMPLES)
    output: list[PriceAnomalyOut] = []
    for key, values in series.items():
        if len(values) < MIN_PRICE_SAMPLES:
            continue
        material_id = key[0]
        unit = unit_labels[key]
        history = values[:-1]
        points = [(float(index), float(price)) for index, (_, price) in enumerate(history)]
        intercept, slope = linear_fit(points)
        expected = max(0, round(intercept + slope * len(history)))
        residuals = [price - (intercept + slope * index) for index, (_, price) in enumerate(history)]
        baseline = max(float(median(price for _, price in history)) * 0.05, 1.0)
        scale = max(pstdev(residuals) if len(residuals) > 1 else 0.0, baseline)
        latest_date, latest_price = values[-1]
        score = abs(latest_price - expected) / scale
        deviation = ((latest_price - expected) / expected * 100) if expected else 0.0
        is_anomaly = score >= 3.0
        direction = "yüksek" if latest_price > expected else "düşük"
        explanation = (
            f"{names[material_id]} ({unit}) son birim fiyatı {latest_price} kuruş; önceki "
            f"{len(history)} kayıttan beklenen {expected} kuruş. Sapma %{round(deviation, 2)}, "
            f"anomali skoru {round(score, 2)}"
            + (f" — beklenenden belirgin şekilde {direction}." if is_anomaly else ".")
        )
        output.append(
            PriceAnomalyOut(
                material_id=material_id,
                material_name=names[material_id],
                unit=unit,
                sample_count=len(values),
                latest_date=latest_date,
                latest_unit_price_kurus=latest_price,
                expected_unit_price_kurus=expected,
                deviation_percent=round(deviation, 2),
                anomaly_score=round(score, 2),
                is_anomaly=is_anomaly,
                next_expected_unit_price_kurus=max(0, round(intercept + slope * (len(history) + 1))),
                explanation=explanation,
                first_date=values[0][0],
            )
        )
    output.sort(key=lambda row: (-row.anomaly_score, row.material_name, row.unit))
    return output, ready_count


# --- B. Yeniden satın alma tahmini ------------------------------------------------------------------


class ReorderOut(ReorderForecast):
    confidence_score: float = 0.0
    irregularity: float = 0.0
    explanation: str = ""
    first_date: date | None = None
    last_date: date | None = None


def reorder_insights(session: Session, as_of: date) -> tuple[list[ReorderOut], int]:
    series: dict[str, list[date]] = defaultdict(list)
    names: dict[str, str] = {}
    for material_id, material_name, purchase_date in session.execute(
        select(Purchase.material_id, Material.name, Purchase.purchase_date)
        .join(Material, Material.id == Purchase.material_id)
        .where(*usable_purchases(), Purchase.purchase_date <= as_of)
        .order_by(Purchase.purchase_date)
    ):
        series[material_id].append(purchase_date)
        names[material_id] = material_name
    ready_count = sum(1 for dates in series.values() if len(set(dates)) >= MIN_REORDER_SAMPLES)
    output: list[ReorderOut] = []
    for material_id, raw_dates in series.items():
        dates = sorted(set(raw_dates))
        if len(dates) < MIN_REORDER_SAMPLES:
            continue
        intervals = [(right - left).days for left, right in pairwise(dates)]
        interval = max(1, round(median(intervals)))
        spread = pstdev(intervals) if len(intervals) > 1 else 0
        variation = spread / interval if interval else 1
        # Düzensiz seride güven düşer: hem etiket hem sayısal skor değişim katsayısına bağlıdır.
        label = "high" if variation <= 0.25 else "medium" if variation <= 0.6 else "low"
        score = round(max(0.05, 1 - variation) * min(1.0, len(dates) / 8), 3)
        expected = dates[-1] + timedelta(days=interval)
        output.append(
            ReorderOut(
                material_id=material_id,
                material_name=names[material_id],
                sample_count=len(dates),
                median_interval_days=interval,
                next_expected_date=expected,
                days_until_expected=(expected - as_of).days,
                confidence=label,
                confidence_score=score,
                irregularity=round(variation, 3),
                explanation=(
                    f"{names[material_id]} için {len(dates)} farklı alış tarihinin medyan aralığı "
                    f"{interval} gün; son alış {dates[-1]}, beklenen sonraki alış {expected}. "
                    f"Aralık değişkenliği {round(variation, 2)} ({label})."
                ),
                first_date=dates[0],
                last_date=dates[-1],
            )
        )
    output.sort(key=lambda row: (row.next_expected_date, row.material_name))
    return output, ready_count


# --- C. Proje bütçe riski -----------------------------------------------------------------------------


class ProjectRiskOut(ProjectRisk):
    confidence_score: float = 0.0
    explanation: str = ""
    first_date: date | None = None


def project_events(session: Session, project_id: str, upto: date) -> list[tuple[date, int]]:
    events: list[tuple[date, int]] = []
    events.extend(
        session.execute(
            select(Purchase.purchase_date, Purchase.total_kurus)
            .join(Material, Material.id == Purchase.material_id)
            .where(
                Purchase.project_id == project_id,
                *usable_purchases(),
                Purchase.purchase_date <= upto,
            )
        ).all()
    )
    # İşçilik tahakkuku: ödeme tarihinden değil çalışma tarihinden.
    events.extend(
        session.execute(
            select(WorkLog.work_date, WorkLog.amount_kurus).where(
                WorkLog.project_id == project_id,
                WorkLog.status == RecordStatus.ACTIVE,
                WorkLog.work_date <= upto,
            )
        ).all()
    )
    events.extend(
        session.execute(
            select(ProjectExpense.expense_date, ProjectExpense.amount_kurus).where(
                ProjectExpense.project_id == project_id,
                ProjectExpense.status == RecordStatus.ACTIVE,
                ProjectExpense.expense_date <= upto,
            )
        ).all()
    )
    events.sort(key=lambda item: (item[0], item[1]))
    return events


def project_insights(session: Session, as_of: date) -> tuple[list[ProjectRiskOut], int]:
    output: list[ProjectRiskOut] = []
    ready_count = 0
    projects = session.scalars(
        select(Project)
        .where(
            Project.status == RecordStatus.ACTIVE,
            Project.project_state == "active",
            Project.budget_kurus.is_not(None),
            Project.budget_kurus > 0,
        )
        .order_by(Project.name, Project.id)
    ).all()
    for project in projects:
        events = project_events(session, project.id, as_of)
        if len(events) < MIN_PROJECT_EVENTS:
            continue
        ready_count += 1
        first_date = events[0][0]
        cumulative = 0
        points: list[tuple[float, float]] = []
        for event_date, amount in events:
            cumulative += amount
            points.append((float((event_date - first_date).days), float(cumulative)))
        intercept, slope = linear_fit(points)
        horizon = float((as_of - first_date).days + 30)
        projected = max(cumulative, round(intercept + slope * horizon))
        budget = project.budget_kurus or 0
        usage = cumulative / budget * 100
        projected_usage = projected / budget * 100
        risk = "high" if projected_usage >= 100 else "medium" if projected_usage >= 80 else "low"
        output.append(
            ProjectRiskOut(
                project_id=project.id,
                project_name=project.name,
                sample_count=len(events),
                current_cost_kurus=cumulative,
                budget_kurus=budget,
                projected_30d_cost_kurus=projected,
                budget_usage_percent=round(usage, 2),
                projected_usage_percent=round(projected_usage, 2),
                risk_level=risk,
                confidence_score=round(min(1.0, len(events) / 12), 3),
                explanation=(
                    f"{project.name}: {len(events)} maliyet olayına göre bugüne kadar {cumulative} "
                    f"kuruş (bütçenin %{round(usage, 1)}'i); 30 gün sonrası için {projected} kuruş "
                    f"(%{round(projected_usage, 1)}) bekleniyor → {risk} risk."
                ),
                first_date=first_date,
            )
        )
    output.sort(key=lambda row: (-row.projected_usage_percent, row.project_name))
    return output, ready_count


# --- D. Firma fiyat karşılaştırması -------------------------------------------------------------------


def supplier_comparisons(session: Session, as_of: date) -> tuple[list[dict], int]:
    series: dict[tuple[str, str], list[tuple[date, str, float, Decimal]]] = defaultdict(list)
    names: dict[str, str] = {}
    labels: dict[tuple[str, str], str] = {}
    supplier_names: dict[str, str] = {}
    for purchase, material_name, supplier_name in session.execute(
        select(Purchase, Material.name, Supplier.name)
        .join(Material, Material.id == Purchase.material_id)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .where(
            *usable_purchases(),
            Purchase.quantity.is_not(None),
            Purchase.quantity > 0,
            Purchase.unit.is_not(None),
            Purchase.purchase_date <= as_of,
        )
        .order_by(Purchase.purchase_date, Purchase.created_at, Purchase.id)
    ):
        key = (purchase.material_id, purchase.unit.strip().casefold())
        series[key].append(
            (
                purchase.purchase_date,
                purchase.supplier_id,
                float(unit_price(purchase)),
                purchase.quantity,
            )
        )
        names[purchase.material_id] = material_name
        labels.setdefault(key, purchase.unit)
        supplier_names[purchase.supplier_id] = supplier_name

    output: list[dict] = []
    ready = 0
    for key, records in sorted(series.items(), key=lambda item: (names[item[0][0]], item[0][1])):
        by_supplier: dict[str, list[tuple[date, float, Decimal]]] = defaultdict(list)
        for day, supplier_id, price, quantity in records:
            by_supplier[supplier_id].append((day, price, quantity))
        eligible = {s: r for s, r in by_supplier.items() if len(r) >= MIN_SUPPLIER_RECORDS}
        if len(eligible) < MIN_SUPPLIER_COUNT:
            continue  # veri yetersiz: sonuç üretilmez
        ready += 1
        used = [(sid, day, price) for sid, rows in eligible.items() for day, price, _ in rows]
        first_day = min(item[1] for item in used)
        reference_day = max(item[1] for item in used)
        points = [(float((day - first_day).days), price) for _, day, price in used]
        intercept, slope = linear_fit(points)
        trend_ref = intercept + slope * (reference_day - first_day).days

        def normalized(
            day: date,
            price: float,
            ref: float = trend_ref,
            a: float = intercept,
            b: float = slope,
            start: date = first_day,
        ) -> float:
            trend = a + b * (day - start).days
            return price * ref / trend if trend > 0 and ref > 0 else price

        suppliers = []
        for supplier_id, rows in sorted(eligible.items()):
            raw = [price for _, price, _ in rows]
            norm = [normalized(day, price) for day, price, _ in rows]
            quantities = [float(q) for _, _, q in rows]
            suppliers.append(
                {
                    "supplier_id": supplier_id,
                    "supplier_name": supplier_names[supplier_id],
                    "record_count": len(rows),
                    "mean_unit_price_kurus": round(sum(raw) / len(raw), 2),
                    "trend_adjusted_unit_price_kurus": round(sum(norm) / len(norm), 2),
                    "median_quantity": round(float(median(quantities)), 3),
                    "first_date": min(day for day, _, _ in rows).isoformat(),
                    "last_date": max(day for day, _, _ in rows).isoformat(),
                }
            )
        suppliers.sort(key=lambda s: (s["trend_adjusted_unit_price_kurus"], s["supplier_id"]))
        caveats = []
        latest_start = max(date.fromisoformat(s["first_date"]) for s in suppliers)
        earliest_end = min(date.fromisoformat(s["last_date"]) for s in suppliers)
        if latest_start > earliest_end:
            caveats.append("period_gap")  # firmaların kayıt dönemleri örtüşmüyor
        quantities = [s["median_quantity"] for s in suppliers]
        if min(quantities) <= 0 or max(quantities) / min(quantities) > MAX_QUANTITY_RATIO:
            caveats.append("quantity_gap")  # miktar farkı fiyatı etkiliyor olabilir
        best, second = suppliers[0], suppliers[1]
        gap = (
            (second["trend_adjusted_unit_price_kurus"] - best["trend_adjusted_unit_price_kurus"])
            / second["trend_adjusted_unit_price_kurus"]
            * 100
            if second["trend_adjusted_unit_price_kurus"]
            else 0.0
        )
        if gap < MIN_PRICE_GAP_PERCENT:
            caveats.append("no_clear_difference")
        comparable = not caveats
        total = sum(s["record_count"] for s in suppliers)
        label = labels[key]
        output.append(
            {
                "material_id": key[0],
                "material_name": names[key[0]],
                "unit": label,
                "comparable": comparable,
                "cheapest_supplier_id": best["supplier_id"] if comparable else None,
                "cheapest_supplier_name": best["supplier_name"] if comparable else None,
                "saving_percent": round(gap, 2) if comparable else None,
                "caveats": caveats,
                "sample_count": total,
                "confidence_score": round(min(1.0, total / 12) * (1.0 if comparable else 0.5), 3),
                "suppliers": suppliers,
                "explanation": (
                    f"{names[key[0]]} ({label}): {best['supplier_name']} tarih etkisi "
                    f"arındırılmış ortalamada %{round(gap, 2)} daha ucuz."
                    if comparable
                    else f"{names[key[0]]} ({label}): 'en ucuz' denemez — {', '.join(caveats)}."
                ),
            }
        )
    return output, ready


# --- E. Personel maaş yükü tahmini -----------------------------------------------------------------------


def payroll_forecast(session: Session, as_of: date) -> tuple[dict | None, int]:
    closed = list(
        session.scalars(
            select(PayrollPeriod)
            .where(PayrollPeriod.status == RecordStatus.ACTIVE, PayrollPeriod.state == "closed")
            .order_by(PayrollPeriod.period_start)
        )
    )
    if len(closed) < MIN_CLOSED_PAYROLL_PERIODS:
        return None, len(closed)
    totals = dict(
        session.execute(
            select(
                PayrollEntry.payroll_period_id,
                func.coalesce(func.sum(PayrollEntry.net_due_kurus), 0),
            )
            .where(PayrollEntry.status == RecordStatus.ACTIVE)
            .group_by(PayrollEntry.payroll_period_id)
        ).all()
    )
    recent = closed[-6:]
    per_day = []
    labor_per_day = []
    history = []
    for period in recent:
        days = (period.period_end - period.period_start).days + 1
        net = int(totals.get(period.id, 0))
        labor = int(
            session.scalar(
                select(func.coalesce(func.sum(WorkLog.amount_kurus), 0)).where(
                    WorkLog.status == RecordStatus.ACTIVE,
                    WorkLog.work_date >= period.period_start,
                    WorkLog.work_date <= period.period_end,
                )
            )
            or 0
        )
        per_day.append(net / days)
        labor_per_day.append(labor / days)
        history.append(
            {"period_start": period.period_start.isoformat(), "days": days, "net_due_kurus": net}
        )
    weights = list(range(1, len(per_day) + 1))  # yeni dönemler daha ağırlıklı
    baseline = sum(w * v for w, v in zip(weights, per_day, strict=True)) / sum(weights)
    labor_baseline = sum(w * v for w, v in zip(weights, labor_per_day, strict=True)) / sum(weights)
    last = closed[-1]
    upcoming = session.scalar(
        select(PayrollPeriod)
        .where(
            PayrollPeriod.status == RecordStatus.ACTIVE,
            PayrollPeriod.state.in_(("draft", "calculated")),
            PayrollPeriod.period_start > last.period_end,
        )
        .order_by(PayrollPeriod.period_start)
    )
    if upcoming is not None:
        start, end = upcoming.period_start, upcoming.period_end
    else:
        start = last.period_end + timedelta(days=1)
        month_end = (last.period_end + timedelta(days=1)).day == 1
        if last.period_start.day == 1 and month_end:
            # Takvim ayına hizalı dönemlerde sonraki dönem de tam takvim ayıdır.
            end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        else:
            end = start + timedelta(days=(last.period_end - last.period_start).days)
    days = (end - start).days + 1

    def month_aligned(first: date, last_day: date) -> bool:
        return first.day == 1 and (last_day + timedelta(days=1)).day == 1

    if month_aligned(start, end) and all(
        month_aligned(p.period_start, p.period_end) for p in recent
    ):
        # Takvim ayı dönemlerinde gün sayısı farkı (28–31) ücreti değiştirmez: dönem toplamı kullanılır.
        totals_list = [item["net_due_kurus"] for item in history]
        estimate = sum(w * v for w, v in zip(weights, totals_list, strict=True)) / sum(weights)
    else:
        estimate = baseline * days
    pace = None
    elapsed = (min(as_of, end) - start).days + 1
    logged = int(
        session.scalar(
            select(func.coalesce(func.sum(WorkLog.amount_kurus), 0)).where(
                WorkLog.status == RecordStatus.ACTIVE,
                WorkLog.work_date >= start,
                WorkLog.work_date <= min(as_of, end),
            )
        )
        or 0
    )
    if elapsed >= 7 and labor_baseline > 0:
        pace = max(0.5, min(1.5, logged / (labor_baseline * elapsed)))
        estimate *= 0.5 + 0.5 * pace  # mevcut puantaj hızı tahmini yarı yarıya etkiler
    mean = sum(per_day) / len(per_day)
    variation = (pstdev(per_day) / mean) if mean else 1.0
    confidence = round(max(0.1, 1 - variation) * min(1.0, len(closed) / 6), 3)
    return (
        {
            "period_start": start,
            "period_end": end,
            "predicted_net_due_kurus": round(estimate),
            "baseline_per_day_kurus": round(baseline, 2),
            "pace_factor": round(pace, 3) if pace is not None else None,
            "logged_labor_so_far_kurus": logged,
            "closed_period_count": len(closed),
            "confidence_score": confidence,
            "history": history,
            "explanation": (
                f"Son {len(recent)} kapanmış dönemin günlük ağırlıklı ortalaması "
                f"{round(baseline)} kuruş; {start}–{end} ({days} gün) için {round(estimate)} "
                "kuruş maaş yükü bekleniyor."
            ),
        },
        len(closed),
    )


# --- F. Personel borç riski ----------------------------------------------------------------------------------


def debt_risks(session: Session, as_of: date) -> tuple[list[dict], int]:
    employee_ids = list(
        session.scalars(
            select(EmployeeFinancialMovement.employee_id)
            .distinct()
            .order_by(EmployeeFinancialMovement.employee_id)
        )
    )
    if not employee_ids:
        return [], 0
    names = dict(
        session.execute(select(Employee.id, Employee.name).where(Employee.id.in_(employee_ids))).all()
    )
    now = compute_positions(session, employee_ids, as_of)
    previous = compute_positions(session, employee_ids, as_of - timedelta(days=30))
    horizon = as_of + timedelta(days=30)
    output = []
    for employee_id in sorted(employee_ids, key=lambda e: (names.get(e, "").casefold(), e)):
        position, before = now[employee_id], previous[employee_id]
        if position.company_owes == 0 and position.employee_owes == 0:
            continue
        co_items = [i for i in position.co_items if i.remaining > 0]
        overdue_co = sum(
            i.remaining for i in co_items if i.movement.due_date and i.movement.due_date < as_of
        )
        upcoming = sum(
            i.remaining
            for i in co_items
            if i.movement.due_date is None or i.movement.due_date <= horizon
        )
        eo_overdue = sum(
            i.remaining
            for i in position.advance_items + position.debt_items
            if i.remaining > 0 and i.movement.due_date and i.movement.due_date < as_of
        )
        growing_co = position.company_owes > before.company_owes * 1.1
        growing_eo = position.employee_owes > before.employee_owes * 1.1
        flags = [
            name
            for name, on in (
                ("overdue_company_debt", overdue_co > 0),
                ("overdue_employee_debt", eo_overdue > 0),
                ("growing_company_debt", growing_co),
                ("growing_employee_debt", growing_eo),
            )
            if on
        ]
        score = len(flags)
        risk = (
            "high"
            if score >= 3 or (overdue_co > 0 and growing_co)
            else "medium"
            if score >= 1
            else "low"
        )
        output.append(
            {
                "employee_id": employee_id,
                "employee_name": names.get(employee_id),
                "company_owes_employee_kurus": position.company_owes,
                "employee_owes_company_kurus": position.employee_owes,
                "unpaid_payroll_kurus": position.unpaid_payroll,
                "payment_need_30d_kurus": upcoming,
                "overdue_company_debt_kurus": overdue_co,
                "overdue_employee_debt_kurus": eo_overdue,
                "company_owes_30d_ago_kurus": before.company_owes,
                "flags": flags,
                "risk_level": risk,
                "confidence_score": 0.8,
                "explanation": (
                    f"Önümüzdeki 30 günde {upcoming} kuruş ödeme ihtiyacı; vadesi geçmiş şirket "
                    f"borcu {overdue_co} kuruş. İşaretler: {', '.join(flags) or 'yok'}. Bu tahmin "
                    "otomatik hareket oluşturmaz."
                ),
            }
        )
    rank = {"high": 0, "medium": 1, "low": 2}
    output.sort(
        key=lambda r: (rank[r["risk_level"]], -r["payment_need_30d_kurus"], r["employee_id"])
    )
    return output, len(employee_ids)


# --- Canlı içgörüler ---------------------------------------------------------------------------------------


class MLInsightsOut(MLInsights):
    price_anomalies: list[PriceAnomalyOut]  # type: ignore[assignment]
    reorder_forecasts: list[ReorderOut]  # type: ignore[assignment]
    project_risks: list[ProjectRiskOut]  # type: ignore[assignment]
    supplier_comparisons: list[dict] = Field(default_factory=list)
    payroll_forecast: dict | None = None
    debt_risks: list[dict] = Field(default_factory=list)


@router.get("/insights", response_model=MLInsightsOut)
def ml_insights(as_of: date | None = None, session: Session = Depends(get_session)):
    effective_date = as_of or date.today()
    prices, price_ready = price_insights(session)
    reorders, reorder_ready = reorder_insights(session, effective_date)
    projects, project_ready = project_insights(session, effective_date)
    suppliers, supplier_ready = supplier_comparisons(session, effective_date)
    forecast, _closed_periods = payroll_forecast(session, effective_date)
    debts, debt_employees = debt_risks(session, effective_date)
    purchase_count = int(
        session.scalar(
            select(func.count(Purchase.id))
            .join(Material, Material.id == Purchase.material_id)
            .where(*usable_purchases())
        )
        or 0
    )
    ready = bool(
        price_ready or reorder_ready or project_ready or supplier_ready or forecast or debt_employees
    )
    message = (
        "Yerel modeller yeterli geçmişe sahip seriler için üretildi."
        if ready
        else "Henüz güvenilir tahmin için yeterli geçmiş veri yok."
    )
    return MLInsightsOut(
        as_of=effective_date,
        status=MLStatus(
            ready=ready,
            purchase_count=purchase_count,
            material_series_ready=price_ready,
            reorder_series_ready=reorder_ready,
            project_series_ready=project_ready,
            minimum_price_samples=MIN_PRICE_SAMPLES,
            minimum_reorder_samples=MIN_REORDER_SAMPLES,
            message=message,
        ),
        price_anomalies=prices,
        reorder_forecasts=reorders,
        project_risks=projects,
        supplier_comparisons=suppliers,
        payroll_forecast=forecast,
        debt_risks=debts,
    )


# --- Çalıştırma, kalıcı sonuç geçmişi ve değerlendirme ---------------------------------------------------------


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _model_output(session: Session, name: str, as_of: date):
    """(tahminler, eğitim_başı, eğitim_sonu, örnek_sayısı, parametreler, metrikler)"""
    in_30 = as_of + timedelta(days=30)
    if name == "price_anomaly":
        rows, ready = price_insights(session)
        preds = [
            (
                "material_unit",
                f"{r.material_id}|{r.unit.strip().casefold()}",
                in_30,
                r.next_expected_unit_price_kurus,
                min(1.0, r.sample_count / 12),
                r.model_dump(mode="json"),
            )
            for r in rows
        ]
        return (
            preds,
            min((r.first_date for r in rows if r.first_date), default=None),
            max((r.latest_date for r in rows), default=None),
            sum(r.sample_count for r in rows),
            {"min_samples": MIN_PRICE_SAMPLES, "anomaly_score_threshold": 3.0},
            {"series_ready": ready, "anomalies": sum(r.is_anomaly for r in rows)},
        )
    if name == "reorder":
        rows, ready = reorder_insights(session, as_of)
        preds = [
            (
                "material",
                r.material_id,
                r.next_expected_date,
                r.days_until_expected,
                r.confidence_score,
                r.model_dump(mode="json"),
            )
            for r in rows
        ]
        return (
            preds,
            min((r.first_date for r in rows if r.first_date), default=None),
            max((r.last_date for r in rows if r.last_date), default=None),
            sum(r.sample_count for r in rows),
            {"min_unique_dates": MIN_REORDER_SAMPLES},
            {"series_ready": ready},
        )
    if name == "project_budget_risk":
        rows, ready = project_insights(session, as_of)
        preds = [
            (
                "project",
                r.project_id,
                in_30,
                r.projected_30d_cost_kurus,
                r.confidence_score,
                r.model_dump(mode="json"),
            )
            for r in rows
        ]
        return (
            preds,
            min((r.first_date for r in rows if r.first_date), default=None),
            as_of if rows else None,
            sum(r.sample_count for r in rows),
            {"min_events": MIN_PROJECT_EVENTS, "horizon_days": 30},
            {"projects_ready": ready, "high_risk": sum(r.risk_level == "high" for r in rows)},
        )
    if name == "supplier_price_comparison":
        rows, ready = supplier_comparisons(session, as_of)
        preds = [
            (
                "material_unit",
                f"{r['material_id']}|{r['unit'].strip().casefold()}",
                None,
                r["saving_percent"],
                r["confidence_score"],
                r,
            )
            for r in rows
        ]
        firsts = [s["first_date"] for r in rows for s in r["suppliers"]]
        lasts = [s["last_date"] for r in rows for s in r["suppliers"]]
        return (
            preds,
            date.fromisoformat(min(firsts)) if firsts else None,
            date.fromisoformat(max(lasts)) if lasts else None,
            sum(r["sample_count"] for r in rows),
            {
                "min_suppliers": MIN_SUPPLIER_COUNT,
                "min_records_per_supplier": MIN_SUPPLIER_RECORDS,
                "max_quantity_ratio": MAX_QUANTITY_RATIO,
                "min_gap_percent": MIN_PRICE_GAP_PERCENT,
            },
            {"series_ready": ready, "comparable": sum(r["comparable"] for r in rows)},
        )
    if name == "payroll_load":
        forecast, closed = payroll_forecast(session, as_of)
        parameters = {"min_closed_periods": MIN_CLOSED_PAYROLL_PERIODS, "history_periods": 6}
        if forecast is None:
            return [], None, None, closed, parameters, {"closed_periods": closed}
        first = date.fromisoformat(forecast["history"][0]["period_start"])
        preds = [
            (
                "payroll",
                "company",
                forecast["period_end"],
                forecast["predicted_net_due_kurus"],
                forecast["confidence_score"],
                forecast,
            )
        ]
        return preds, first, as_of, closed, parameters, {"closed_periods": closed}
    rows, employees = debt_risks(session, as_of)
    preds = [
        (
            "employee",
            r["employee_id"],
            in_30,
            r["payment_need_30d_kurus"],
            r["confidence_score"],
            r,
        )
        for r in rows
    ]
    return (
        preds,
        None,
        as_of if rows else None,
        employees,
        {"horizon_days": 30, "growth_threshold": 1.1},
        {
            "employees_with_balance": len(rows),
            "high_risk": sum(r["risk_level"] == "high" for r in rows),
        },
    )


def run_model(session: Session, name: str, as_of: date) -> MlRun:
    preds, trained_from, trained_to, samples, parameters, metrics = _model_output(
        session, name, as_of
    )
    metrics = {**metrics, "prediction_count": len(preds)}
    if not preds:
        metrics["status"] = "insufficient_data"
    run = MlRun(
        model_name=name,
        model_version=MODEL_VERSION,
        trained_from=trained_from,
        trained_to=trained_to,
        sample_count=int(samples),
        parameters=_json_safe({**parameters, "as_of": as_of}),
        metrics=_json_safe(metrics),
    )
    session.add(run)
    session.flush()
    for entity_type, entity_id, target, value, confidence, explanation in preds:
        session.add(
            MlPrediction(
                ml_run_id=run.id,
                prediction_type=name,
                entity_type=entity_type,
                entity_id=entity_id,
                prediction_date=as_of,
                target_date=target,
                predicted_value=None if value is None else round(float(value), 4),
                confidence=None if confidence is None else round(float(confidence), 4),
                explanation=_json_safe(explanation),
            )
        )
    return run


def _actual_for(session: Session, prediction: MlPrediction, as_of: date) -> float | None:
    ptype, entity = prediction.prediction_type, prediction.entity_id
    target = prediction.target_date
    if ptype == "price_anomaly":
        material_id, unit = entity.split("|", 1)
        rows = session.execute(
            select(Purchase)
            .join(Material, Material.id == Purchase.material_id)
            .where(
                *usable_purchases(),
                Purchase.material_id == material_id,
                Purchase.purchase_date > prediction.prediction_date,
                Purchase.purchase_date <= as_of,
            )
            .order_by(Purchase.purchase_date, Purchase.created_at, Purchase.id)
        )
        for (purchase,) in rows:
            if purchase.unit and purchase.unit.strip().casefold() == unit and purchase.quantity:
                return float(unit_price(purchase))
        return None
    if ptype == "reorder":
        first = session.scalar(
            select(func.min(Purchase.purchase_date))
            .join(Material, Material.id == Purchase.material_id)
            .where(
                *usable_purchases(),
                Purchase.material_id == entity,
                Purchase.purchase_date > prediction.prediction_date,
                Purchase.purchase_date <= as_of,
            )
        )
        return float((first - prediction.prediction_date).days) if first else None
    if ptype == "project_budget_risk":
        if target is None or as_of < target:
            return None
        return float(sum(amount for _, amount in project_events(session, entity, target)))
    if ptype == "payroll_load":
        if target is None or as_of < target:
            return None
        start = date.fromisoformat((prediction.explanation or {})["period_start"])
        period = session.scalar(
            select(PayrollPeriod).where(
                PayrollPeriod.status == RecordStatus.ACTIVE,
                PayrollPeriod.period_start == start,
                PayrollPeriod.state.in_(("finalized", "closed")),
            )
        )
        if period is None:
            return None
        return float(
            session.scalar(
                select(func.coalesce(func.sum(PayrollEntry.net_due_kurus), 0)).where(
                    PayrollEntry.payroll_period_id == period.id,
                    PayrollEntry.status == RecordStatus.ACTIVE,
                )
            )
            or 0
        )
    if ptype == "employee_debt_risk":
        if target is None or as_of < target:
            return None
        paid = 0
        for movement in load_effective(session, [entity], target).get(entity, []):
            if (
                classify(movement) == "paid"
                and prediction.prediction_date < movement.movement_date <= target
            ):
                paid += movement.amount_kurus
        return float(paid)
    return None  # supplier_price_comparison gerçekleşme değeri taşımaz


def evaluate_predictions(session: Session, as_of: date) -> int:
    pending = session.scalars(
        select(MlPrediction)
        .where(MlPrediction.actual_value.is_(None), MlPrediction.prediction_date < as_of)
        .order_by(MlPrediction.created_at, MlPrediction.id)
    ).all()
    done = 0
    now = datetime.now(UTC)
    for prediction in pending:
        actual = _actual_for(session, prediction, as_of)
        if actual is None:
            continue
        prediction.actual_value = actual
        prediction.evaluated_at = now
        done += 1
    return done


def evaluation_metrics(session: Session) -> dict[str, dict]:
    rows = session.execute(
        select(
            MlPrediction.prediction_type, MlPrediction.predicted_value, MlPrediction.actual_value
        ).where(
            MlPrediction.actual_value.is_not(None), MlPrediction.predicted_value.is_not(None)
        )
    ).all()
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for ptype, predicted, actual in rows:
        grouped[ptype].append((predicted, actual))
    result = {}
    for ptype, pairs in grouped.items():
        errors = [abs(p - a) for p, a in pairs]
        pct = [abs(p - a) / abs(a) * 100 for p, a in pairs if a]
        result[ptype] = {
            "evaluated": len(pairs),
            "mean_absolute_error": round(sum(errors) / len(errors), 2),
            "mean_absolute_percent_error": round(sum(pct) / len(pct), 2) if pct else None,
        }
    return result


class RunRequest(BaseModel):
    as_of: date | None = None
    models: list[ModelName] | None = None


class FeedbackRequest(BaseModel):
    feedback: Literal["useful", "not_useful", "wrong"]
    note: str | None = Field(default=None, max_length=500)


class EvaluateRequest(BaseModel):
    as_of: date | None = None


def run_out(run: MlRun) -> dict:
    return {
        "id": run.id,
        "model_name": run.model_name,
        "model_version": run.model_version,
        "trained_from": run.trained_from,
        "trained_to": run.trained_to,
        "sample_count": run.sample_count,
        "parameters": run.parameters,
        "metrics": run.metrics,
        "created_at": run.created_at,
    }


def prediction_out(p: MlPrediction) -> dict:
    return {
        "id": p.id,
        "ml_run_id": p.ml_run_id,
        "prediction_type": p.prediction_type,
        "entity_type": p.entity_type,
        "entity_id": p.entity_id,
        "prediction_date": p.prediction_date,
        "target_date": p.target_date,
        "predicted_value": p.predicted_value,
        "confidence": p.confidence,
        "explanation": p.explanation,
        "actual_value": p.actual_value,
        "evaluated_at": p.evaluated_at,
        "user_feedback": p.user_feedback,
        "created_at": p.created_at,
    }


REQUIREMENTS = {
    "price_anomaly": f"en az {MIN_PRICE_SAMPLES} kayıtlı malzeme+birim serisi",
    "reorder": f"en az {MIN_REORDER_SAMPLES} benzersiz satın alma tarihi",
    "project_budget_risk": f"bütçeli aktif proje ve en az {MIN_PROJECT_EVENTS} maliyet olayı",
    "supplier_price_comparison": (
        f"aynı malzeme+birimde en az {MIN_SUPPLIER_COUNT} firma, her biri en az "
        f"{MIN_SUPPLIER_RECORDS} kayıt"
    ),
    "payroll_load": f"en az {MIN_CLOSED_PAYROLL_PERIODS} kapanmış maaş dönemi",
    "employee_debt_risk": "personel finans hareketi",
}


@router.get("/status")
def ml_status(as_of: date | None = None, session: Session = Depends(get_session)):
    day = as_of or date.today()
    insights = ml_insights(day, session)
    ready = {
        "price_anomaly": insights.status.material_series_ready,
        "reorder": insights.status.reorder_series_ready,
        "project_budget_risk": insights.status.project_series_ready,
        "supplier_price_comparison": len(insights.supplier_comparisons),
        "payroll_load": 1 if insights.payroll_forecast else 0,
        "employee_debt_risk": len(insights.debt_risks),
    }
    metrics = evaluation_metrics(session)
    models = []
    for name in MODEL_NAMES:
        last = session.scalar(
            select(MlRun)
            .where(MlRun.model_name == name)
            .order_by(MlRun.created_at.desc(), MlRun.id.desc())
        )
        models.append(
            {
                "model_name": name,
                "model_version": MODEL_VERSION,
                "ready": ready[name] > 0,
                "ready_series": ready[name],
                "requirement": REQUIREMENTS[name],
                "last_run_id": last.id if last else None,
                "last_run_at": last.created_at if last else None,
                "last_run_prediction_count": (last.metrics or {}).get("prediction_count")
                if last
                else None,
                "evaluation": metrics.get(name),
            }
        )
    return {
        "local_only": True,
        "external_services": [],
        "as_of": day,
        "ready": insights.status.ready,
        "run_count": int(session.scalar(select(func.count(MlRun.id))) or 0),
        "prediction_count": int(session.scalar(select(func.count(MlPrediction.id))) or 0),
        "models": models,
    }


@router.post("/run")
def run_models(
    payload: RunRequest = Body(default_factory=RunRequest), session: Session = Depends(get_session)
):
    day = payload.as_of or date.today()
    evaluated = evaluate_predictions(session, day)
    runs = [run_model(session, name, day) for name in (payload.models or MODEL_NAMES)]
    add_audit(
        session,
        "ml",
        runs[0].id if runs else "ml",
        "run",
        {"as_of": day, "models": [r.model_name for r in runs]},
    )
    session.commit()
    counts = dict(
        session.execute(
            select(MlPrediction.ml_run_id, func.count(MlPrediction.id))
            .where(MlPrediction.ml_run_id.in_([r.id for r in runs]))
            .group_by(MlPrediction.ml_run_id)
        ).all()
    )
    return {
        "as_of": day,
        "evaluated_predictions": evaluated,
        "runs": [{**run_out(r), "prediction_count": int(counts.get(r.id, 0))} for r in runs],
    }


@router.post("/evaluate")
def evaluate(
    payload: EvaluateRequest = Body(default_factory=EvaluateRequest),
    session: Session = Depends(get_session),
):
    evaluated = evaluate_predictions(session, payload.as_of or date.today())
    session.commit()
    return {"evaluated_predictions": evaluated, "metrics": evaluation_metrics(session)}


@router.get("/runs")
def list_runs(
    session: Session = Depends(get_session),
    model_name: str | None = Query(default=None, pattern="^[a-z_]{1,40}$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = select(MlRun)
    if model_name:
        query = query.where(MlRun.model_name == model_name)
    rows = session.scalars(
        query.order_by(MlRun.created_at.desc(), MlRun.id).limit(limit).offset(offset)
    )
    return [run_out(r) for r in rows]


@router.get("/predictions")
def list_predictions(
    session: Session = Depends(get_session),
    prediction_type: str | None = Query(default=None, pattern="^[a-z_]{1,40}$"),
    entity_id: str | None = Query(default=None, max_length=80),
    run_id: str | None = None,
    evaluated: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(MlPrediction)
    if prediction_type:
        query = query.where(MlPrediction.prediction_type == prediction_type)
    if entity_id:
        query = query.where(MlPrediction.entity_id == entity_id)
    if run_id:
        query = query.where(MlPrediction.ml_run_id == run_id)
    if evaluated is True:
        query = query.where(MlPrediction.actual_value.is_not(None))
    elif evaluated is False:
        query = query.where(MlPrediction.actual_value.is_(None))
    rows = session.scalars(
        query.order_by(MlPrediction.created_at.desc(), MlPrediction.id).limit(limit).offset(offset)
    )
    return [prediction_out(p) for p in rows]


@router.post("/predictions/{prediction_id}/feedback")
def prediction_feedback(
    prediction_id: str, payload: FeedbackRequest, session: Session = Depends(get_session)
):
    prediction = session.get(MlPrediction, prediction_id)
    if prediction is None:
        raise ApiError("not_found", "Tahmin bulunamadı.", 404)
    prediction.user_feedback = payload.feedback
    add_audit(
        session,
        "ml_prediction",
        prediction.id,
        "feedback",
        {"feedback": payload.feedback, "note": payload.note},
    )
    session.commit()
    return prediction_out(prediction)

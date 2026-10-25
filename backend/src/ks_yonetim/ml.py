from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from statistics import median, pstdev

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import require_sidecar_token
from .database import get_session
from .models import Material, Project, ProjectExpense, Purchase, RecordStatus, WorkLog
from .schemas import MLInsights, MLStatus, PriceAnomaly, ProjectRisk, ReorderForecast

router = APIRouter(prefix="/api/v1/analytics/ml", dependencies=[Depends(require_sidecar_token)])
MIN_PRICE_SAMPLES = 5
MIN_REORDER_SAMPLES = 4
MIN_PROJECT_EVENTS = 4


def linear_fit(points: list[tuple[float, float]]) -> tuple[float, float]:
    count = len(points)
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    slope = (
        sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
        if denominator
        else 0.0
    )
    return mean_y - slope * mean_x, slope


def price_insights(session: Session) -> tuple[list[PriceAnomaly], int]:
    series: dict[tuple[str, str], list[tuple[date, int]]] = defaultdict(list)
    names: dict[str, str] = {}
    rows = session.execute(
        select(Purchase, Material.name)
        .join(Material, Material.id == Purchase.material_id)
        .where(
            Purchase.status == RecordStatus.ACTIVE,
            Purchase.quantity.is_not(None),
            Purchase.quantity > 0,
            Purchase.unit.is_not(None),
        )
        .order_by(Purchase.purchase_date, Purchase.created_at)
    )
    for purchase, material_name in rows:
        unit_price = purchase.unit_price_kurus
        if unit_price is None:
            unit_price = int(Decimal(purchase.total_kurus) / purchase.quantity)
        series[(purchase.material_id, purchase.unit)].append((purchase.purchase_date, unit_price))
        names[purchase.material_id] = material_name

    ready_count = sum(1 for values in series.values() if len(values) >= MIN_PRICE_SAMPLES)
    output: list[PriceAnomaly] = []
    for (material_id, unit), values in series.items():
        if len(values) < MIN_PRICE_SAMPLES:
            continue
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
        output.append(
            PriceAnomaly(
                material_id=material_id,
                material_name=names[material_id],
                unit=unit,
                sample_count=len(values),
                latest_date=latest_date,
                latest_unit_price_kurus=latest_price,
                expected_unit_price_kurus=expected,
                deviation_percent=round(deviation, 2),
                anomaly_score=round(score, 2),
                is_anomaly=score >= 3.0,
                next_expected_unit_price_kurus=max(0, round(intercept + slope * (len(history) + 1))),
            )
        )
    return sorted(output, key=lambda row: (-row.anomaly_score, row.material_name)), ready_count


def reorder_insights(session: Session, as_of: date) -> tuple[list[ReorderForecast], int]:
    series: dict[str, list[date]] = defaultdict(list)
    names: dict[str, str] = {}
    for material_id, material_name, purchase_date in session.execute(
        select(Purchase.material_id, Material.name, Purchase.purchase_date)
        .join(Material, Material.id == Purchase.material_id)
        .where(Purchase.status == RecordStatus.ACTIVE, Purchase.purchase_date <= as_of)
        .order_by(Purchase.purchase_date)
    ):
        series[material_id].append(purchase_date)
        names[material_id] = material_name
    ready_count = sum(1 for dates in series.values() if len(set(dates)) >= MIN_REORDER_SAMPLES)
    output: list[ReorderForecast] = []
    for material_id, raw_dates in series.items():
        dates = sorted(set(raw_dates))
        if len(dates) < MIN_REORDER_SAMPLES:
            continue
        intervals = [(right - left).days for left, right in pairwise(dates)]
        interval = max(1, round(median(intervals)))
        spread = pstdev(intervals) if len(intervals) > 1 else 0
        variation = spread / interval if interval else 1
        confidence = "high" if variation <= 0.25 else "medium" if variation <= 0.6 else "low"
        expected = dates[-1] + timedelta(days=interval)
        output.append(
            ReorderForecast(
                material_id=material_id,
                material_name=names[material_id],
                sample_count=len(dates),
                median_interval_days=interval,
                next_expected_date=expected,
                days_until_expected=(expected - as_of).days,
                confidence=confidence,
            )
        )
    return sorted(output, key=lambda row: row.next_expected_date), ready_count


def project_insights(session: Session, as_of: date) -> tuple[list[ProjectRisk], int]:
    output: list[ProjectRisk] = []
    ready_count = 0
    projects = session.scalars(
        select(Project).where(
            Project.status == RecordStatus.ACTIVE,
            Project.project_state == "active",
            Project.budget_kurus.is_not(None),
            Project.budget_kurus > 0,
        )
    ).all()
    for project in projects:
        events: list[tuple[date, int]] = []
        events.extend(
            session.execute(
                select(Purchase.purchase_date, Purchase.total_kurus).where(
                    Purchase.project_id == project.id,
                    Purchase.status == RecordStatus.ACTIVE,
                    Purchase.purchase_date <= as_of,
                )
            ).all()
        )
        events.extend(
            session.execute(
                select(WorkLog.work_date, WorkLog.amount_kurus).where(
                    WorkLog.project_id == project.id,
                    WorkLog.status == RecordStatus.ACTIVE,
                    WorkLog.work_date <= as_of,
                )
            ).all()
        )
        events.extend(
            session.execute(
                select(ProjectExpense.expense_date, ProjectExpense.amount_kurus).where(
                    ProjectExpense.project_id == project.id,
                    ProjectExpense.status == RecordStatus.ACTIVE,
                    ProjectExpense.expense_date <= as_of,
                )
            ).all()
        )
        if len(events) < MIN_PROJECT_EVENTS:
            continue
        ready_count += 1
        events.sort(key=lambda item: item[0])
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
            ProjectRisk(
                project_id=project.id,
                project_name=project.name,
                sample_count=len(events),
                current_cost_kurus=cumulative,
                budget_kurus=budget,
                projected_30d_cost_kurus=projected,
                budget_usage_percent=round(usage, 2),
                projected_usage_percent=round(projected_usage, 2),
                risk_level=risk,
            )
        )
    return sorted(output, key=lambda row: (-row.projected_usage_percent, row.project_name)), ready_count


@router.get("/insights", response_model=MLInsights)
def ml_insights(
    as_of: date | None = None, session: Session = Depends(get_session)
) -> MLInsights:
    effective_date = as_of or date.today()
    prices, price_ready = price_insights(session)
    reorders, reorder_ready = reorder_insights(session, effective_date)
    projects, project_ready = project_insights(session, effective_date)
    purchase_count = len(
        session.scalars(select(Purchase.id).where(Purchase.status == RecordStatus.ACTIVE)).all()
    )
    ready = bool(price_ready or reorder_ready or project_ready)
    message = (
        "Yerel modeller yeterli geçmişe sahip seriler için üretildi."
        if ready
        else "Henüz güvenilir tahmin için yeterli geçmiş veri yok."
    )
    return MLInsights(
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
    )

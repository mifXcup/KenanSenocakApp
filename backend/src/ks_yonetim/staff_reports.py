"""Personel/maaş/işçilik/ML raporları: JSON, XLSX ve PDF aynı ReportTable üreticisinden çıkar."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import clock
from .api import ApiError, require_sidecar_token
from .exports import Column, ReportTable
from .finance import (
    BUCKET_NAMES,
    CO,
    EO,
    aging_rows,
    compute_positions,
    statement_lines,
)
from .models import (
    Employee,
    EmployeeFinancialMovement,
    MlPrediction,
    PayrollEntry,
    PayrollPeriod,
    Project,
    RecordStatus,
    Site,
    WorkLog,
)
from .payroll import payroll_period_table
from .report_base import build_report as shared_build_report
from .report_base import register_report_routes
from .reports import AGING_LABELS

router = APIRouter(prefix="/api/v1/reports/staff", dependencies=[Depends(require_sidecar_token)])


@dataclass
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    employee_id: str | None = None
    project_id: str | None = None
    site_id: str | None = None
    payroll_period_id: str | None = None
    horizon_days: int = 30

    def as_dict(self) -> dict:
        return {
            "date_from": self.date_from,
            "date_to": self.date_to,
            "employee_id": self.employee_id,
            "project_id": self.project_id,
            "site_id": self.site_id,
            "payroll_period_id": self.payroll_period_id,
        }

    @property
    def as_of(self) -> date:
        return self.date_to or clock.business_today()


def get_filters(
    date_from: date | None = None,
    date_to: date | None = None,
    employee_id: str | None = Query(default=None, max_length=36),
    project_id: str | None = Query(default=None, max_length=36),
    site_id: str | None = Query(default=None, max_length=36),
    payroll_period_id: str | None = Query(default=None, max_length=36),
    horizon_days: int = Query(30, ge=1, le=365),
) -> Filters:
    if date_from and date_to and date_from > date_to:
        raise ApiError("invalid_range", "Başlangıç tarihi bitiş tarihinden sonra olamaz.", 422)
    return Filters(date_from, date_to, employee_id, project_id, site_id, payroll_period_id, horizon_days)


def sum_totals(rows: list[dict], columns: list[Column]) -> dict:
    return {
        c.key: sum(int(row.get(c.key) or 0) for row in rows)
        for c in columns
        if c.kind == "money" or c.key.endswith("_count")
    }


def names_for(session: Session, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    return dict(session.execute(select(Employee.id, Employee.name).where(Employee.id.in_(ids))).all())


def employee_scope(session: Session, f: Filters) -> list[str]:
    if f.employee_id:
        return [f.employee_id]
    return list(
        session.scalars(
            select(EmployeeFinancialMovement.employee_id)
            .distinct()
            .order_by(EmployeeFinancialMovement.employee_id)
        )
    )


def iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


# --- Raporlar --------------------------------------------------------------------------------------


def report_employee_statement(session: Session, f: Filters) -> ReportTable:
    if not f.employee_id:
        raise ApiError("employee_required", "Hesap ekstresi için employee_id gereklidir.", 422)
    employee = session.get(Employee, f.employee_id)
    if employee is None:
        raise ApiError("not_found", "Personel bulunamadı.", 404)
    lines, totals = statement_lines(session, f.employee_id, f.date_from, f.date_to)
    columns = [
        Column("movement_date", "Tarih", "date"),
        Column("movement_type", "Tür"),
        Column("direction", "Yön"),
        Column("amount_kurus", "Tutar", "money"),
        Column("due_date", "Vade", "date"),
        Column("company_owes_delta_kurus", "Şirket borcu değişimi", "money"),
        Column("employee_owes_delta_kurus", "Personel borcu değişimi", "money"),
        Column("running_company_owes_kurus", "Şirket borcu bakiye", "money"),
        Column("running_employee_owes_kurus", "Personel borcu bakiye", "money"),
        Column("note", "Not"),
    ]
    rows = [
        {**line, "movement_date": iso(line["movement_date"]), "due_date": iso(line["due_date"])}
        for line in lines
    ]
    return ReportTable(
        "employee-statement",
        f"Personel Hesap Ekstresi: {employee.name}",
        columns,
        rows,
        {
            "company_owes_delta_kurus": totals["company_owes_delta_kurus"],
            "employee_owes_delta_kurus": totals["employee_owes_delta_kurus"],
            "running_company_owes_kurus": totals["closing_company_owes_kurus"],
            "running_employee_owes_kurus": totals["closing_employee_owes_kurus"],
        },
        f.as_dict(),
    )


def report_payroll_period_summary(session: Session, f: Filters) -> ReportTable:
    if not f.payroll_period_id:
        raise ApiError("period_required", "Dönem özeti için payroll_period_id gereklidir.", 422)
    period = session.get(PayrollPeriod, f.payroll_period_id)
    if period is None or period.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "Maaş dönemi bulunamadı.", 404)
    table = payroll_period_table(session, period)
    if f.employee_id:
        table.rows = [r for r in table.rows if r["employee_id"] == f.employee_id]
        table.totals = sum_totals(table.rows, table.columns)
    table.filters = f.as_dict()
    return table


def report_unpaid_payroll(session: Session, f: Filters) -> ReportTable:
    query = (
        select(PayrollEntry, PayrollPeriod, Employee.name)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollEntry.payroll_period_id)
        .join(Employee, Employee.id == PayrollEntry.employee_id)
        .where(
            PayrollEntry.status == RecordStatus.ACTIVE,
            PayrollPeriod.status == RecordStatus.ACTIVE,
            PayrollPeriod.state.in_(("finalized", "closed")),
            PayrollEntry.remaining_kurus > 0,
        )
        .order_by(PayrollPeriod.period_start, func.lower(Employee.name), PayrollEntry.id)
    )
    if f.payroll_period_id:
        query = query.where(PayrollEntry.payroll_period_id == f.payroll_period_id)
    if f.employee_id:
        query = query.where(PayrollEntry.employee_id == f.employee_id)
    if f.date_from:
        query = query.where(PayrollPeriod.period_end >= f.date_from)
    if f.date_to:
        query = query.where(PayrollPeriod.period_start <= f.date_to)
    columns = [
        Column("period_title", "Dönem"),
        Column("period_state", "Durum"),
        Column("employee_name", "Personel"),
        Column("net_due_kurus", "Net ödenecek", "money"),
        Column("paid_kurus", "Ödenen", "money"),
        Column("remaining_kurus", "Kalan", "money"),
    ]
    rows = [
        {
            "period_title": period.title,
            "period_state": period.state,
            "employee_name": name,
            "net_due_kurus": entry.net_due_kurus,
            "paid_kurus": entry.paid_kurus,
            "remaining_kurus": entry.remaining_kurus,
        }
        for entry, period, name in session.execute(query)
    ]
    return ReportTable("unpaid-payroll", "Ödenmemiş Maaşlar", columns, rows, sum_totals(rows, columns), f.as_dict())


def _pool_report(session: Session, f: Filters, name: str, title: str, attr: str) -> ReportTable:
    ids = employee_scope(session, f)
    positions = compute_positions(session, ids, f.as_of)
    names = names_for(session, ids)
    columns = [
        Column("employee_name", "Personel"),
        Column("total_kurus", "Toplam verilen/doğan", "money"),
        Column("recovered_kurus", "Mahsup/ödenen", "money"),
        Column("outstanding_kurus", "Kalan", "money"),
        Column("oldest_due_date", "En eski vade", "date"),
    ]
    rows = []
    for employee_id in sorted(ids, key=lambda e: (names.get(e, "").casefold(), e)):
        items = getattr(positions[employee_id], attr)
        if not items:
            continue
        total = sum(i.movement.amount_kurus for i in items)
        outstanding = sum(i.remaining for i in items)
        dues = [i.movement.due_date for i in items if i.remaining > 0 and i.movement.due_date]
        rows.append(
            {
                "employee_name": names.get(employee_id),
                "total_kurus": total,
                "recovered_kurus": total - outstanding,
                "outstanding_kurus": outstanding,
                "oldest_due_date": iso(min(dues)) if dues else None,
            }
        )
    rows = [r for r in rows if r["outstanding_kurus"] > 0 or f.employee_id]
    return ReportTable(name, title, columns, rows, sum_totals(rows, columns), f.as_dict())


def report_employee_advances(session: Session, f: Filters) -> ReportTable:
    return _pool_report(session, f, "employee-advances", "Personel Avansları", "advance_items")


def report_employee_debts(session: Session, f: Filters) -> ReportTable:
    return _pool_report(session, f, "employee-debts", "Personel Borçları", "debt_items")


def report_payment_history(session: Session, f: Filters) -> ReportTable:
    types = ("payroll_payment", "advance", "employee_debt_payment", "reversal")
    query = (
        select(EmployeeFinancialMovement, Employee.name)
        .join(Employee, Employee.id == EmployeeFinancialMovement.employee_id)
        .where(
            EmployeeFinancialMovement.status == RecordStatus.ACTIVE,
            EmployeeFinancialMovement.movement_type.in_(types),
        )
        .order_by(
            EmployeeFinancialMovement.movement_date,
            EmployeeFinancialMovement.created_at,
            EmployeeFinancialMovement.id,
        )
    )
    for column, value in (
        (EmployeeFinancialMovement.employee_id, f.employee_id),
        (EmployeeFinancialMovement.project_id, f.project_id),
        (EmployeeFinancialMovement.site_id, f.site_id),
        (EmployeeFinancialMovement.payroll_period_id, f.payroll_period_id),
    ):
        if value:
            query = query.where(column == value)
    if f.date_from:
        query = query.where(EmployeeFinancialMovement.movement_date >= f.date_from)
    if f.date_to:
        query = query.where(EmployeeFinancialMovement.movement_date <= f.date_to)
    fetched = list(session.execute(query))
    voided = {m.reversed_movement_id for m, _ in fetched if m.movement_type == "reversal"}
    columns = [
        Column("movement_date", "Tarih", "date"),
        Column("employee_name", "Personel"),
        Column("movement_type", "Tür"),
        Column("amount_kurus", "Tutar", "money"),
        Column("voided", "Hükümsüz"),
        Column("note", "Not"),
    ]
    rows = [
        {
            "movement_date": iso(m.movement_date),
            "employee_name": name,
            "movement_type": m.movement_type,
            "amount_kurus": m.amount_kurus,
            "voided": "evet" if m.id in voided else "",
            "note": m.note,
        }
        for m, name in fetched
        if m.movement_type != "reversal"
    ]
    # Toplam yalnız hükümsüz olmayan nakit hareketlerdir.
    effective = sum(
        m.amount_kurus for m, _ in fetched if m.movement_type != "reversal" and m.id not in voided
    )
    return ReportTable(
        "payment-history",
        "Personel Ödeme Geçmişi",
        columns,
        rows,
        {"amount_kurus": effective},
        f.as_dict(),
    )


def _labor_filters(f: Filters):
    conditions = [WorkLog.status == RecordStatus.ACTIVE]
    for column, value in (
        (WorkLog.employee_id, f.employee_id),
        (WorkLog.project_id, f.project_id),
        (WorkLog.site_id, f.site_id),
    ):
        if value:
            conditions.append(column == value)
    if f.date_from:
        conditions.append(WorkLog.work_date >= f.date_from)
    if f.date_to:
        conditions.append(WorkLog.work_date <= f.date_to)
    return conditions


LABOR_SUMS = (
    func.count(WorkLog.id),
    func.coalesce(func.sum(WorkLog.normal_hours), 0),
    func.coalesce(func.sum(WorkLog.overtime_hours), 0),
    func.coalesce(func.sum(WorkLog.amount_kurus), 0),
)


def _labor_report(session: Session, f: Filters, name: str, title: str, group_col, name_col, label: str, empty: str):
    columns = [
        Column("name", label),
        Column("log_count", "Kayıt", "number"),
        Column("normal_hours", "Normal saat", "number"),
        Column("overtime_hours", "Fazla mesai saat", "number"),
        Column("amount_kurus", "İşçilik tahakkuku", "money"),
    ]
    query = select(name_col, *LABOR_SUMS).where(*_labor_filters(f)).group_by(group_col, name_col)
    query = query.order_by(func.sum(WorkLog.amount_kurus).desc(), name_col)
    return query, columns


def report_project_labor(session: Session, f: Filters) -> ReportTable:
    query, columns = _labor_report(session, f, "project-labor", "Proje Bazlı İşçilik", WorkLog.project_id, Project.name, "Proje", "Projesiz")
    query = query.select_from(WorkLog).outerjoin(Project, Project.id == WorkLog.project_id)
    rows = [
        {"name": n or "Projesiz", "log_count": c, "normal_hours": float(nh), "overtime_hours": float(oh), "amount_kurus": int(a)}
        for n, c, nh, oh, a in session.execute(query)
    ]
    totals = sum_totals(rows, columns)
    totals["normal_hours"] = round(sum(r["normal_hours"] for r in rows), 2)
    totals["overtime_hours"] = round(sum(r["overtime_hours"] for r in rows), 2)
    return ReportTable("project-labor", "Proje Bazlı İşçilik", columns, rows, totals, f.as_dict())


def report_site_labor(session: Session, f: Filters) -> ReportTable:
    query, columns = _labor_report(session, f, "site-labor", "Şantiye Bazlı İşçilik", WorkLog.site_id, Site.name, "Şantiye", "Şantiyesiz")
    query = query.select_from(WorkLog).outerjoin(Site, Site.id == WorkLog.site_id)
    rows = [
        {"name": n or "Şantiyesiz", "log_count": c, "normal_hours": float(nh), "overtime_hours": float(oh), "amount_kurus": int(a)}
        for n, c, nh, oh, a in session.execute(query)
    ]
    totals = sum_totals(rows, columns)
    totals["normal_hours"] = round(sum(r["normal_hours"] for r in rows), 2)
    totals["overtime_hours"] = round(sum(r["overtime_hours"] for r in rows), 2)
    return ReportTable("site-labor", "Şantiye Bazlı İşçilik", columns, rows, totals, f.as_dict())


def report_monthly_staff_cost(session: Session, f: Filters) -> ReportTable:
    month = func.strftime("%Y-%m", WorkLog.work_date)
    labor = {
        label: int(amount)
        for label, amount in session.execute(
            select(month, func.coalesce(func.sum(WorkLog.amount_kurus), 0))
            .where(*_labor_filters(f))
            .group_by(month)
        )
    }
    payroll: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    pquery = (
        select(PayrollPeriod.period_start, func.sum(PayrollEntry.gross_earning_kurus), func.sum(PayrollEntry.net_due_kurus))
        .join(PayrollEntry, PayrollEntry.payroll_period_id == PayrollPeriod.id)
        .where(
            PayrollPeriod.status == RecordStatus.ACTIVE,
            PayrollPeriod.state.in_(("finalized", "closed")),
            PayrollEntry.status == RecordStatus.ACTIVE,
        )
        .group_by(PayrollPeriod.id, PayrollPeriod.period_start)
    )
    if f.employee_id:
        pquery = pquery.where(PayrollEntry.employee_id == f.employee_id)
    if f.payroll_period_id:
        pquery = pquery.where(PayrollPeriod.id == f.payroll_period_id)
    if f.date_from:
        pquery = pquery.where(PayrollPeriod.period_end >= f.date_from)
    if f.date_to:
        pquery = pquery.where(PayrollPeriod.period_start <= f.date_to)
    for start, gross, net in session.execute(pquery):
        key = start.strftime("%Y-%m")
        payroll[key][0] += int(gross or 0)
        payroll[key][1] += int(net or 0)
    columns = [
        Column("month", "Ay"),
        Column("labor_accrual_kurus", "Puantaj işçilik tahakkuku", "money"),
        Column("payroll_gross_kurus", "Kesinleşmiş maaş brüt", "money"),
        Column("payroll_net_kurus", "Kesinleşmiş maaş net", "money"),
    ]
    rows = [
        {
            "month": key,
            "labor_accrual_kurus": labor.get(key, 0),
            "payroll_gross_kurus": payroll[key][0] if key in payroll else 0,
            "payroll_net_kurus": payroll[key][1] if key in payroll else 0,
        }
        for key in sorted(set(labor) | set(payroll))
    ]
    return ReportTable("monthly-staff-cost", "Aylık Toplam Personel Maliyeti", columns, rows, sum_totals(rows, columns), f.as_dict())


def report_upcoming_payments(session: Session, f: Filters) -> ReportTable:
    day = clock.business_today() if f.date_to is None else f.date_to
    horizon = day + timedelta(days=f.horizon_days)
    ids = employee_scope(session, f)
    positions = compute_positions(session, ids, day)
    names = names_for(session, ids)
    columns = [
        Column("employee_name", "Personel"),
        Column("due_date", "Vade", "date"),
        Column("movement_type", "Tür"),
        Column("remaining_kurus", "Ödenecek", "money"),
        Column("days_overdue", "Gecikme (gün)", "number"),
    ]
    rows = []
    for employee_id in ids:
        for item in positions[employee_id].co_items:
            due = item.movement.due_date
            if item.remaining <= 0 or (due is not None and due > horizon):
                continue
            rows.append(
                {
                    "employee_name": names.get(employee_id),
                    "due_date": iso(due),
                    "movement_type": item.movement.movement_type,
                    "remaining_kurus": item.remaining,
                    "days_overdue": max(0, (day - due).days) if due else None,
                    "_sort": (due or date.max, names.get(employee_id, "").casefold(), item.movement.id),
                }
            )
    rows.sort(key=lambda r: r["_sort"])
    for row in rows:
        row.pop("_sort")
    return ReportTable("upcoming-payments", "Yaklaşan Maaş Ödemeleri", columns, rows, sum_totals(rows, columns), f.as_dict())


def report_debt_aging(session: Session, f: Filters) -> ReportTable:
    ids = employee_scope(session, f)
    positions = compute_positions(session, ids, f.as_of)
    names = names_for(session, ids)
    bucket_keys = [BUCKET_NAMES[key] for key in AGING_LABELS]
    labels = {BUCKET_NAMES[k]: v for k, v in AGING_LABELS.items()}
    columns = [Column("employee_name", "Personel"), Column("side", "Taraf")]
    columns += [Column(key, labels[key], "money") for key in bucket_keys]
    columns.append(Column("total_kurus", "Toplam", "money"))
    rows = []
    for employee_id in sorted(ids, key=lambda e: (names.get(e, "").casefold(), e)):
        items = aging_rows(positions[employee_id], f.as_of)
        for side, side_label in ((CO, "Şirket → personel"), (EO, "Personel → şirket")):
            buckets = dict.fromkeys(bucket_keys, 0)
            for item in items:
                if item["side"] == side:
                    buckets[item["bucket"]] += item["remaining_kurus"]
            total = sum(buckets.values())
            if total:
                rows.append({"employee_name": names.get(employee_id), "side": side_label, **buckets, "total_kurus": total})
    return ReportTable("debt-aging", "Personel Borç Yaşlandırma", columns, rows, sum_totals(rows, columns), f.as_dict())


def report_ml_vs_actual(session: Session, f: Filters) -> ReportTable:
    query = (
        select(MlPrediction)
        .where(MlPrediction.actual_value.is_not(None))
        .order_by(MlPrediction.prediction_date, MlPrediction.prediction_type, MlPrediction.id)
    )
    if f.date_from:
        query = query.where(MlPrediction.prediction_date >= f.date_from)
    if f.date_to:
        query = query.where(MlPrediction.prediction_date <= f.date_to)
    columns = [
        Column("prediction_type", "Model"),
        Column("entity_id", "Kayıt"),
        Column("prediction_date", "Tahmin tarihi", "date"),
        Column("target_date", "Hedef tarih", "date"),
        Column("predicted_value", "Tahmin", "number"),
        Column("actual_value", "Gerçekleşen", "number"),
        Column("error", "Hata", "number"),
        Column("error_percent", "Hata %", "number"),
        Column("user_feedback", "Geri bildirim"),
    ]
    rows = []
    for p in session.scalars(query):
        error = None if p.predicted_value is None else round(p.predicted_value - p.actual_value, 2)
        rows.append(
            {
                "prediction_type": p.prediction_type,
                "entity_id": p.entity_id,
                "prediction_date": iso(p.prediction_date),
                "target_date": iso(p.target_date),
                "predicted_value": p.predicted_value,
                "actual_value": p.actual_value,
                "error": error,
                "error_percent": round(error / p.actual_value * 100, 2) if error is not None and p.actual_value else None,
                "user_feedback": p.user_feedback,
            }
        )
    errors = [abs(r["error"]) for r in rows if r["error"] is not None]
    totals = {"error": round(sum(errors) / len(errors), 2) if errors else 0}  # ortalama mutlak hata
    return ReportTable("ml-prediction-vs-actual", "ML Tahmin ve Gerçekleşme Karşılaştırması", columns, rows, totals, f.as_dict())


BUILDERS = {
    "employee-statement": report_employee_statement,
    "payroll-period-summary": report_payroll_period_summary,
    "unpaid-payroll": report_unpaid_payroll,
    "employee-advances": report_employee_advances,
    "employee-debts": report_employee_debts,
    "payment-history": report_payment_history,
    "project-labor": report_project_labor,
    "site-labor": report_site_labor,
    "monthly-staff-cost": report_monthly_staff_cost,
    "upcoming-payments": report_upcoming_payments,
    "debt-aging": report_debt_aging,
    "ml-prediction-vs-actual": report_ml_vs_actual,
}


def build_report(session: Session, name: str, f: Filters) -> ReportTable:
    return shared_build_report(BUILDERS, session, name, f)


register_report_routes(router, BUILDERS, get_filters)

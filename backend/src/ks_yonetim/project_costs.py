"""Proje ve şantiye maliyet özetleri.

İşçilik maliyeti çalışma (tahakkuk) tarihinden ve yalnız aktif puantaj kayıtlarından gelir; maaş
ödemesi veya maaş dönemi bu tutarı ne değiştirir ne de ikinci kez sayar. Açılış borcu kayıtları ve
iptal edilenler hariçtir.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .api import ApiError, require_active, require_sidecar_token
from .database import get_session
from .models import (
    Employee,
    ExpenseCategory,
    Project,
    ProjectExpense,
    Purchase,
    RecordStatus,
    Site,
    WorkLog,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])
OPENING_PREFIX = "opening:"


class ProjectCostSummaryOut(BaseModel):
    project_id: str
    purchase_kurus: int
    labor_accrual_kurus: int
    labor_kurus: int  # v0.2.0 istemcileri için labor_accrual_kurus ile aynı
    shipping_kurus: int
    installation_kurus: int
    site_kurus: int
    other_kurus: int
    total_cost_kurus: int
    budget_kurus: int | None
    budget_variance_kurus: int | None
    contract_amount_kurus: int | None
    estimated_profit_kurus: int | None
    profit_margin_percent: float | None


class SiteCostSummaryOut(BaseModel):
    site_id: str
    project_id: str | None
    purchase_kurus: int
    labor_accrual_kurus: int
    shipping_kurus: int
    installation_kurus: int
    site_kurus: int
    other_kurus: int
    total_cost_kurus: int
    note: str


def _scalar(session: Session, statement) -> int:
    return int(session.scalar(statement) or 0)


def _expenses(session: Session, column, value: str, date_from, date_to) -> dict[ExpenseCategory, int]:
    query = (
        select(ProjectExpense.category, func.sum(ProjectExpense.amount_kurus))
        .where(column == value, ProjectExpense.status == RecordStatus.ACTIVE)
        .group_by(ProjectExpense.category)
    )
    if date_from:
        query = query.where(ProjectExpense.expense_date >= date_from)
    if date_to:
        query = query.where(ProjectExpense.expense_date <= date_to)
    return {category: int(total) for category, total in session.execute(query).all()}


def _labor(session: Session, column, value: str, date_from, date_to) -> int:
    query = select(func.sum(WorkLog.amount_kurus)).where(
        column == value, WorkLog.status == RecordStatus.ACTIVE
    )
    if date_from:
        query = query.where(WorkLog.work_date >= date_from)
    if date_to:
        query = query.where(WorkLog.work_date <= date_to)
    return _scalar(session, query)


def project_cost_summary(
    session: Session, project: Project, date_from: date | None = None, date_to: date | None = None
) -> ProjectCostSummaryOut:
    purchase_query = select(func.sum(Purchase.total_kurus)).where(
        Purchase.project_id == project.id,
        Purchase.status == RecordStatus.ACTIVE,
        ~Purchase.idempotency_key.like(f"{OPENING_PREFIX}%"),
    )
    if date_from:
        purchase_query = purchase_query.where(Purchase.purchase_date >= date_from)
    if date_to:
        purchase_query = purchase_query.where(Purchase.purchase_date <= date_to)
    purchase = _scalar(session, purchase_query)
    labor = _labor(session, WorkLog.project_id, project.id, date_from, date_to)
    expenses = _expenses(session, ProjectExpense.project_id, project.id, date_from, date_to)
    shipping = expenses.get(ExpenseCategory.SHIPPING, 0)
    installation = expenses.get(ExpenseCategory.INSTALLATION, 0)
    site = expenses.get(ExpenseCategory.SITE, 0)
    other = expenses.get(ExpenseCategory.OTHER, 0)
    total = purchase + labor + shipping + installation + site + other
    contract = project.contract_amount_kurus
    profit = contract - total if contract is not None else None
    margin = round(profit / contract * 100, 2) if profit is not None and contract else None
    return ProjectCostSummaryOut(
        project_id=project.id,
        purchase_kurus=purchase,
        labor_accrual_kurus=labor,
        labor_kurus=labor,
        shipping_kurus=shipping,
        installation_kurus=installation,
        site_kurus=site,
        other_kurus=other,
        total_cost_kurus=total,
        budget_kurus=project.budget_kurus,
        budget_variance_kurus=(project.budget_kurus - total)
        if project.budget_kurus is not None
        else None,
        contract_amount_kurus=contract,
        estimated_profit_kurus=profit,
        profit_margin_percent=margin,
    )


@router.get("/projects/{project_id}/cost-summary", response_model=ProjectCostSummaryOut)
def get_project_cost_summary(
    project_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
):
    project = require_active(session, Project, project_id, "Proje")
    if date_from and date_to and date_from > date_to:
        raise ApiError("invalid_range", "Başlangıç tarihi bitiş tarihinden sonra olamaz.", 422)
    return project_cost_summary(session, project, date_from, date_to)


@router.get("/projects/{project_id}/labor-breakdown")
def get_labor_breakdown(
    project_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
):
    project = require_active(session, Project, project_id, "Proje")
    filters = [WorkLog.project_id == project.id, WorkLog.status == RecordStatus.ACTIVE]
    if date_from:
        filters.append(WorkLog.work_date >= date_from)
    if date_to:
        filters.append(WorkLog.work_date <= date_to)
    sums = (
        func.coalesce(func.sum(WorkLog.normal_hours), 0),
        func.coalesce(func.sum(WorkLog.overtime_hours), 0),
        func.count(WorkLog.id),
        func.coalesce(func.sum(WorkLog.amount_kurus), 0),
    )

    def row(values) -> dict:
        return {
            "normal_hours": str(values[0]),
            "overtime_hours": str(values[1]),
            "log_count": int(values[2]),
            "amount_kurus": int(values[3]),
        }

    by_employee = [
        {"employee_id": employee_id, "employee_name": name, **row(values)}
        for employee_id, name, *values in session.execute(
            select(WorkLog.employee_id, Employee.name, *sums)
            .join(Employee, Employee.id == WorkLog.employee_id)
            .where(*filters)
            .group_by(WorkLog.employee_id, Employee.name)
            .order_by(func.sum(WorkLog.amount_kurus).desc(), Employee.name)
        )
    ]
    month = func.strftime("%Y-%m", WorkLog.work_date)
    by_month = [
        {"month": label, **row(values)}
        for label, *values in session.execute(
            select(month, *sums).where(*filters).group_by(month).order_by(month)
        )
    ]
    by_site = [
        {"site_id": site_id, "site_name": name, **row(values)}
        for site_id, name, *values in session.execute(
            select(WorkLog.site_id, Site.name, *sums)
            .outerjoin(Site, Site.id == WorkLog.site_id)
            .where(*filters)
            .group_by(WorkLog.site_id, Site.name)
            .order_by(func.sum(WorkLog.amount_kurus).desc())
        )
    ]
    by_status = [
        {"work_status": status, **row(values)}
        for status, *values in session.execute(
            select(WorkLog.work_status, *sums)
            .where(*filters)
            .group_by(WorkLog.work_status)
            .order_by(WorkLog.work_status)
        )
    ]
    total = sum(item["amount_kurus"] for item in by_employee)
    return {
        "project_id": project.id,
        "date_from": date_from,
        "date_to": date_to,
        "labor_accrual_kurus": total,
        "by_employee": by_employee,
        "by_month": by_month,
        "by_site": by_site,
        "by_status": by_status,
    }


@router.get("/sites/{site_id}/cost-summary", response_model=SiteCostSummaryOut)
def get_site_cost_summary(
    site_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
):
    site = require_active(session, Site, site_id, "Şantiye")
    labor = _labor(session, WorkLog.site_id, site.id, date_from, date_to)
    expenses = _expenses(session, ProjectExpense.site_id, site.id, date_from, date_to)
    shipping = expenses.get(ExpenseCategory.SHIPPING, 0)
    installation = expenses.get(ExpenseCategory.INSTALLATION, 0)
    site_cost = expenses.get(ExpenseCategory.SITE, 0)
    other = expenses.get(ExpenseCategory.OTHER, 0)
    return SiteCostSummaryOut(
        site_id=site.id,
        project_id=site.project_id,
        purchase_kurus=0,
        labor_accrual_kurus=labor,
        shipping_kurus=shipping,
        installation_kurus=installation,
        site_kurus=site_cost,
        other_kurus=other,
        total_cost_kurus=labor + shipping + installation + site_cost + other,
        note="Satın almalar şantiyeye değil projeye bağlanır; şantiye toplamına dahil değildir.",
    )

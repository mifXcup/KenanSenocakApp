from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_active, require_sidecar_token
from .database import get_session
from .models import (
    Employee,
    EmployeePayment,
    ExpenseCategory,
    Project,
    ProjectExpense,
    Purchase,
    RecordStatus,
    Site,
    WorkLog,
)
from .schemas import (
    EmployeePaymentCreate,
    EmployeePaymentRead,
    ProjectCostSummary,
    ProjectExpenseCreate,
    ProjectExpenseRead,
    SiteCreate,
    SiteRead,
    WorkLogCreate,
    WorkLogRead,
)
from .wages import load_rate_book

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])


@router.post("/sites", response_model=SiteRead, status_code=201)
def create_site(payload: SiteCreate, session: Session = Depends(get_session)) -> Site:
    if payload.project_id:
        require_active(session, Project, payload.project_id, "Proje")
    site = Site(**payload.model_dump())
    session.add(site)
    session.flush()
    add_audit(session, "site", site.id, "created")
    session.commit()
    session.refresh(site)
    return site


@router.get("/sites", response_model=list[SiteRead])
def list_sites(
    session: Session = Depends(get_session),
    project_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(Site).where(Site.status == RecordStatus.ACTIVE)
    if project_id:
        query = query.where(Site.project_id == project_id)
    return session.scalars(query.order_by(Site.name).limit(limit).offset(offset)).all()


def validate_site_project(site: Site, project_id: str | None) -> None:
    if site.project_id and site.project_id != project_id:
        raise ApiError("site_project_mismatch", "Şantiye seçilen projeye bağlı değil.", 409)


@router.post("/work-logs", response_model=WorkLogRead, status_code=201)
def create_work_log(payload: WorkLogCreate, session: Session = Depends(get_session)) -> WorkLog:
    employee = require_active(session, Employee, payload.employee_id, "Personel")
    if payload.project_id:
        require_active(session, Project, payload.project_id, "Proje")
    if payload.site_id:
        site = require_active(session, Site, payload.site_id, "Şantiye")
        validate_site_project(site, payload.project_id)
    amount = payload.amount_kurus
    if amount is None:
        rate = load_rate_book(session, [employee.id]).at(employee.id, payload.work_date)
        if rate is None:
            raise ApiError(
                "missing_labor_rate",
                "Tutar girilmeli veya personelin o tarihte geçerli ücreti bulunmalıdır.",
                422,
            )
        divisor = {"hourly": Decimal(1), "daily": Decimal(8), "monthly": Decimal(240)}[
            rate.wage_type
        ]
        amount = int(
            (Decimal(rate.rate_kurus) * payload.hours / divisor).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
        )
    data = payload.model_dump(exclude={"amount_kurus"})
    work_log = WorkLog(**data, amount_kurus=amount)
    session.add(work_log)
    session.flush()
    add_audit(session, "work_log", work_log.id, "created", {"amount_kurus": amount})
    session.commit()
    session.refresh(work_log)
    return work_log


@router.get("/work-logs", response_model=list[WorkLogRead])
def list_work_logs(
    session: Session = Depends(get_session),
    employee_id: str | None = None,
    project_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(WorkLog).where(WorkLog.status == RecordStatus.ACTIVE)
    if employee_id:
        query = query.where(WorkLog.employee_id == employee_id)
    if project_id:
        query = query.where(WorkLog.project_id == project_id)
    return session.scalars(
        query.order_by(WorkLog.work_date.desc(), WorkLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/work-logs/{work_log_id}/cancel", response_model=WorkLogRead)
def cancel_work_log(work_log_id: str, session: Session = Depends(get_session)) -> WorkLog:
    work_log = require_active(session, WorkLog, work_log_id, "Çalışma kaydı")
    work_log.status = RecordStatus.CANCELLED
    add_audit(session, "work_log", work_log.id, "cancelled")
    session.commit()
    session.refresh(work_log)
    return work_log


@router.post("/employee-payments", response_model=EmployeePaymentRead, status_code=201)
def create_employee_payment(
    payload: EmployeePaymentCreate, session: Session = Depends(get_session)
) -> EmployeePayment:
    require_active(session, Employee, payload.employee_id, "Personel")
    payment = EmployeePayment(**payload.model_dump())
    session.add(payment)
    session.flush()
    add_audit(session, "employee_payment", payment.id, "created")
    session.commit()
    session.refresh(payment)
    return payment


@router.get("/employee-payments", response_model=list[EmployeePaymentRead])
def list_employee_payments(
    session: Session = Depends(get_session),
    employee_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(EmployeePayment)
    if employee_id:
        query = query.where(EmployeePayment.employee_id == employee_id)
    return session.scalars(
        query.order_by(EmployeePayment.payment_date.desc(), EmployeePayment.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/employee-payments/{payment_id}/reverse", response_model=EmployeePaymentRead)
def reverse_employee_payment(
    payment_id: str, session: Session = Depends(get_session)
) -> EmployeePayment:
    payment = require_active(session, EmployeePayment, payment_id, "Personel ödemesi")
    payment.status = RecordStatus.REVERSED
    add_audit(session, "employee_payment", payment.id, "reversed")
    session.commit()
    session.refresh(payment)
    return payment


@router.post("/project-expenses", response_model=ProjectExpenseRead, status_code=201)
def create_project_expense(
    payload: ProjectExpenseCreate, session: Session = Depends(get_session)
) -> ProjectExpense:
    require_active(session, Project, payload.project_id, "Proje")
    if payload.site_id:
        site = require_active(session, Site, payload.site_id, "Şantiye")
        validate_site_project(site, payload.project_id)
    expense = ProjectExpense(**payload.model_dump())
    session.add(expense)
    session.flush()
    add_audit(session, "project_expense", expense.id, "created")
    session.commit()
    session.refresh(expense)
    return expense


@router.get("/project-expenses", response_model=list[ProjectExpenseRead])
def list_project_expenses(
    session: Session = Depends(get_session),
    project_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(ProjectExpense).where(ProjectExpense.status == RecordStatus.ACTIVE)
    if project_id:
        query = query.where(ProjectExpense.project_id == project_id)
    return session.scalars(
        query.order_by(ProjectExpense.expense_date.desc(), ProjectExpense.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/project-expenses/{expense_id}/cancel", response_model=ProjectExpenseRead)
def cancel_project_expense(
    expense_id: str, session: Session = Depends(get_session)
) -> ProjectExpense:
    expense = require_active(session, ProjectExpense, expense_id, "Proje gideri")
    expense.status = RecordStatus.CANCELLED
    add_audit(session, "project_expense", expense.id, "cancelled")
    session.commit()
    session.refresh(expense)
    return expense


def sum_value(session: Session, statement) -> int:
    return int(session.scalar(statement) or 0)


@router.get("/projects/{project_id}/cost-summary", response_model=ProjectCostSummary)
def project_cost_summary(
    project_id: str, session: Session = Depends(get_session)
) -> ProjectCostSummary:
    project = require_active(session, Project, project_id, "Proje")
    purchase = sum_value(
        session,
        select(func.sum(Purchase.total_kurus)).where(
            Purchase.project_id == project_id, Purchase.status == RecordStatus.ACTIVE
        ),
    )
    labor = sum_value(
        session,
        select(func.sum(WorkLog.amount_kurus)).where(
            WorkLog.project_id == project_id, WorkLog.status == RecordStatus.ACTIVE
        ),
    )
    expenses = dict(
        session.execute(
            select(ProjectExpense.category, func.sum(ProjectExpense.amount_kurus))
            .where(
                ProjectExpense.project_id == project_id,
                ProjectExpense.status == RecordStatus.ACTIVE,
            )
            .group_by(ProjectExpense.category)
        ).all()
    )
    shipping = int(expenses.get(ExpenseCategory.SHIPPING, 0))
    installation = int(expenses.get(ExpenseCategory.INSTALLATION, 0))
    site = int(expenses.get(ExpenseCategory.SITE, 0))
    other = int(expenses.get(ExpenseCategory.OTHER, 0))
    total = purchase + labor + shipping + installation + site + other
    return ProjectCostSummary(
        project_id=project.id,
        purchase_kurus=purchase,
        labor_kurus=labor,
        shipping_kurus=shipping,
        installation_kurus=installation,
        site_kurus=site,
        other_kurus=other,
        total_cost_kurus=total,
        budget_kurus=project.budget_kurus,
        budget_variance_kurus=(project.budget_kurus - total) if project.budget_kurus is not None else None,
        contract_amount_kurus=project.contract_amount_kurus,
        estimated_profit_kurus=(project.contract_amount_kurus - total)
        if project.contract_amount_kurus is not None
        else None,
    )

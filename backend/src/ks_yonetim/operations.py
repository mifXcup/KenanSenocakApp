from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_active, require_sidecar_token
from .database import get_session
from .models import (
    Project,
    ProjectExpense,
    RecordStatus,
    Site,
)
from .schemas import (
    ProjectExpenseCreate,
    ProjectExpenseRead,
    SiteCreate,
    SiteRead,
)

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

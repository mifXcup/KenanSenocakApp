"""Proje bütçesi, ek işler, satın alma yaşam döngüsü, kârlılık ve maliyet detayı.

Kavramlar:
- Gerçekleşen: teslim alınan satın alma + işçilik tahakkuku + proje giderleri.
- Taahhüt: planlı/siparişli satın almanın tamamı ve kısmi tesliminin teslim edilmemiş kısmı.
- Kalan tahmin: kategori bütçesinden gerçekleşen ve taahhüt düşüldükten sonra kalan (negatif olmaz).
- Tahmini bitiş maliyeti = gerçekleşen + taahhüt + kalan tahmin.
Revize sözleşme bedeli = sözleşme + yalnız onaylı ek işler.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import clock
from .api import ApiError, add_audit, cancel_purchase, require_active, require_sidecar_token
from .customers import project_collection_summary
from .database import get_session
from .models import (
    CustomerFinancialMovement,
    ExpenseCategory,
    Material,
    Project,
    ProjectBudgetLine,
    ProjectBudgetRevision,
    ProjectChangeOrder,
    ProjectCostForecast,
    ProjectExpense,
    Purchase,
    PurchaseReceipt,
    RecordStatus,
    WorkLog,
)
from .project_costs import OPENING_PREFIX
from .receipts import add_receipt, quantity_warnings
from .schemas import OrmModel

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])

BUDGET_CATEGORIES = (
    "material",
    "labor",
    "shipping",
    "installation",
    "subcontractor",
    "site",
    "waste_rework",
    "other",
)
BudgetCategory = Literal[
    "material",
    "labor",
    "shipping",
    "installation",
    "subcontractor",
    "site",
    "waste_rework",
    "other",
]
EXPENSE_TO_BUDGET = {
    ExpenseCategory.SHIPPING: "shipping",
    ExpenseCategory.INSTALLATION: "installation",
    ExpenseCategory.SITE: "site",
    ExpenseCategory.OTHER: "other",
    ExpenseCategory.SUBCONTRACT: "subcontractor",
    ExpenseCategory.REWORK: "waste_rework",
}
PURCHASE_TRANSITIONS = {
    "planned": {"ordered", "partially_received", "received", "cancelled"},
    "ordered": {"partially_received", "received", "cancelled"},
    "partially_received": {"partially_received", "received", "cancelled"},
    "received": {"cancelled"},
    "cancelled": set(),
}
COMMITTING_STATES = ("planned", "ordered", "partially_received")


# --- Bütçe satırları --------------------------------------------------------------------------------


class BudgetLineCreate(BaseModel):
    category: BudgetCategory
    title: str = Field(min_length=2, max_length=180)
    amount_kurus: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=2000)


class BudgetLineUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    amount_kurus: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, min_length=3, max_length=255)

    @model_validator(mode="after")
    def validate_patch(self) -> BudgetLineUpdate:
        changed = self.model_fields_set - {"reason"}
        if not changed:
            raise ValueError("En az bir alan gönderilmelidir.")
        if "amount_kurus" in changed and self.amount_kurus is None:
            raise ValueError("Tutar boş bırakılamaz.")
        if "title" in changed and self.title is None:
            raise ValueError("Başlık boş bırakılamaz.")
        if "amount_kurus" in changed and not self.reason:
            raise ValueError("Bütçe revizyonu için gerekçe (reason) zorunludur.")
        return self


class BudgetLineRead(OrmModel):
    id: str
    project_id: str
    category: str
    title: str
    amount_kurus: int
    original_amount_kurus: int
    revision_no: int
    note: str | None
    status: RecordStatus


class BudgetRevisionRead(OrmModel):
    id: str
    budget_line_id: str
    revision_no: int
    previous_amount_kurus: int | None
    amount_kurus: int
    reason: str | None
    created_at: datetime


def _budget_line(session: Session, project_id: str, line_id: str) -> ProjectBudgetLine:
    line = session.get(ProjectBudgetLine, line_id)
    if line is None or line.project_id != project_id:
        raise ApiError("not_found", "Bütçe satırı bulunamadı.", 404)
    return line


@router.post("/projects/{project_id}/budget-lines", response_model=BudgetLineRead, status_code=201)
def create_budget_line(
    project_id: str, payload: BudgetLineCreate, session: Session = Depends(get_session)
):
    project = require_active(session, Project, project_id, "Proje")
    line = ProjectBudgetLine(
        project_id=project.id,
        category=payload.category,
        title=payload.title,
        amount_kurus=payload.amount_kurus,
        original_amount_kurus=payload.amount_kurus,
        revision_no=1,
        note=payload.note,
    )
    session.add(line)
    session.flush()
    session.add(
        ProjectBudgetRevision(
            budget_line_id=line.id,
            revision_no=1,
            previous_amount_kurus=None,
            amount_kurus=line.amount_kurus,
            reason="Başlangıç bütçesi",
        )
    )
    add_audit(
        session, "project_budget_line", line.id, "created",
        {"project_id": project.id, "category": line.category, "amount_kurus": line.amount_kurus},
    )
    session.commit()
    session.refresh(line)
    return line


@router.get("/projects/{project_id}/budget-lines")
def list_budget_lines(
    project_id: str, include_cancelled: bool = False, session: Session = Depends(get_session)
):
    project = require_active(session, Project, project_id, "Proje")
    query = select(ProjectBudgetLine).where(ProjectBudgetLine.project_id == project.id)
    if not include_cancelled:
        query = query.where(ProjectBudgetLine.status == RecordStatus.ACTIVE)
    lines = list(session.scalars(query.order_by(ProjectBudgetLine.created_at, ProjectBudgetLine.id)))
    live = [line for line in lines if line.status == RecordStatus.ACTIVE]
    by_category = []
    for category in BUDGET_CATEGORIES:
        chosen = [line for line in live if line.category == category]
        if chosen:
            by_category.append(
                {
                    "category": category,
                    "original_kurus": sum(line.original_amount_kurus for line in chosen),
                    "revised_kurus": sum(line.amount_kurus for line in chosen),
                }
            )
    return {
        "project_id": project.id,
        "original_total_kurus": sum(line.original_amount_kurus for line in live),
        "revised_total_kurus": sum(line.amount_kurus for line in live),
        "by_category": by_category,
        "lines": [BudgetLineRead.model_validate(line) for line in lines],
    }


@router.patch("/projects/{project_id}/budget-lines/{line_id}", response_model=BudgetLineRead)
def update_budget_line(
    project_id: str,
    line_id: str,
    payload: BudgetLineUpdate,
    session: Session = Depends(get_session),
):
    require_active(session, Project, project_id, "Proje")
    line = _budget_line(session, project_id, line_id)
    if line.status != RecordStatus.ACTIVE:
        raise ApiError("budget_line_cancelled", "İptal edilmiş bütçe satırı düzenlenemez.", 409)
    changes = payload.model_dump(exclude_unset=True, exclude={"reason"})
    before = {key: getattr(line, key) for key in changes}
    revised = "amount_kurus" in changes and changes["amount_kurus"] != line.amount_kurus
    previous = line.amount_kurus
    for key, value in changes.items():
        setattr(line, key, value)
    if revised:
        line.revision_no += 1
        session.add(
            ProjectBudgetRevision(
                budget_line_id=line.id,
                revision_no=line.revision_no,
                previous_amount_kurus=previous,
                amount_kurus=line.amount_kurus,
                reason=payload.reason,
            )
        )
    add_audit(
        session, "project_budget_line", line.id, "revised" if revised else "updated",
        {"before": before, "after": changes, "reason": payload.reason},
    )
    session.commit()
    session.refresh(line)
    return line


@router.post("/projects/{project_id}/budget-lines/{line_id}/cancel", response_model=BudgetLineRead)
def cancel_budget_line(project_id: str, line_id: str, session: Session = Depends(get_session)):
    require_active(session, Project, project_id, "Proje")
    line = _budget_line(session, project_id, line_id)
    if line.status != RecordStatus.ACTIVE:
        raise ApiError("budget_line_cancelled", "Bütçe satırı zaten iptal edilmiş.", 409)
    line.status = RecordStatus.CANCELLED
    add_audit(session, "project_budget_line", line.id, "cancelled")
    session.commit()
    session.refresh(line)
    return line


@router.get(
    "/projects/{project_id}/budget-lines/{line_id}/revisions",
    response_model=list[BudgetRevisionRead],
)
def list_budget_revisions(project_id: str, line_id: str, session: Session = Depends(get_session)):
    require_active(session, Project, project_id, "Proje")
    line = _budget_line(session, project_id, line_id)
    return session.scalars(
        select(ProjectBudgetRevision)
        .where(ProjectBudgetRevision.budget_line_id == line.id)
        .order_by(ProjectBudgetRevision.revision_no)
    ).all()


# --- Ek işler / kapsam değişikliği ------------------------------------------------------------------


class ChangeOrderCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    amount_kurus: int

    @model_validator(mode="after")
    def validate_amount(self) -> ChangeOrderCreate:
        if self.amount_kurus == 0:
            raise ValueError("Ek iş tutarı sıfır olamaz.")
        return self


class ChangeOrderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    amount_kurus: int | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> ChangeOrderUpdate:
        if not self.model_fields_set:
            raise ValueError("En az bir alan gönderilmelidir.")
        if "amount_kurus" in self.model_fields_set and not self.amount_kurus:
            raise ValueError("Ek iş tutarı sıfır olamaz.")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("Başlık boş bırakılamaz.")
        return self


class ChangeOrderDecision(BaseModel):
    note: str | None = Field(default=None, max_length=255)


class ChangeOrderRead(OrmModel):
    id: str
    project_id: str
    title: str
    description: str | None
    amount_kurus: int
    change_state: str
    decided_at: datetime | None
    decision_note: str | None
    status: RecordStatus


def _change_order(session: Session, project_id: str, order_id: str) -> ProjectChangeOrder:
    order = session.get(ProjectChangeOrder, order_id)
    if order is None or order.project_id != project_id:
        raise ApiError("not_found", "Ek iş bulunamadı.", 404)
    return order


def approved_change_total(session: Session, project_id: str) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(ProjectChangeOrder.amount_kurus), 0)).where(
                ProjectChangeOrder.project_id == project_id,
                ProjectChangeOrder.change_state == "approved",
                ProjectChangeOrder.status == RecordStatus.ACTIVE,
            )
        )
        or 0
    )


def revised_contract(project: Project, approved_total: int) -> int | None:
    if project.contract_amount_kurus is None and approved_total == 0:
        return None
    return (project.contract_amount_kurus or 0) + approved_total


def _transition(
    session: Session, order: ProjectChangeOrder, target: str, note: str | None
) -> ProjectChangeOrder:
    allowed = {
        "draft": {"approved", "rejected", "cancelled"},
        "approved": {"cancelled"},
        "rejected": set(),
        "cancelled": set(),
    }
    if target not in allowed[order.change_state]:
        raise ApiError(
            "invalid_transition",
            f"Ek iş '{order.change_state}' durumundan '{target}' durumuna geçirilemez.",
            409,
            {"from": order.change_state, "to": target},
        )
    if order.change_state == "approved" and target == "cancelled":
        accruals = session.scalars(
            select(CustomerFinancialMovement.id).where(
                CustomerFinancialMovement.change_order_id == order.id,
                CustomerFinancialMovement.status == RecordStatus.ACTIVE,
                CustomerFinancialMovement.movement_type == "accrual",
            )
        ).all()
        voided = set(
            session.scalars(
                select(CustomerFinancialMovement.reversed_movement_id).where(
                    CustomerFinancialMovement.reversed_movement_id.in_(accruals or [""]),
                    CustomerFinancialMovement.status == RecordStatus.ACTIVE,
                )
            )
        )
        open_accruals = [a for a in accruals if a not in voided]
        if open_accruals:
            raise ApiError(
                "change_order_has_accruals",
                "Müşteriye tahakkuk edilmiş onaylı ek iş önce tahakkuk ters kaydıyla çözülmelidir.",
                409,
                {"movement_ids": open_accruals},
            )
    before = order.change_state
    order.change_state = target
    order.decided_at = datetime.now(UTC)
    order.decision_note = note
    add_audit(
        session, "project_change_order", order.id, target,
        {"from": before, "amount_kurus": order.amount_kurus, "note": note},
    )
    session.commit()
    session.refresh(order)
    return order


@router.post(
    "/projects/{project_id}/change-orders", response_model=ChangeOrderRead, status_code=201
)
def create_change_order(
    project_id: str, payload: ChangeOrderCreate, session: Session = Depends(get_session)
):
    project = require_active(session, Project, project_id, "Proje")
    order = ProjectChangeOrder(project_id=project.id, **payload.model_dump())
    session.add(order)
    session.flush()
    add_audit(
        session, "project_change_order", order.id, "created", {"amount_kurus": order.amount_kurus}
    )
    session.commit()
    session.refresh(order)
    return order


@router.get("/projects/{project_id}/change-orders")
def list_change_orders(
    project_id: str,
    state: Literal["draft", "approved", "rejected", "cancelled"] | None = None,
    session: Session = Depends(get_session),
):
    project = require_active(session, Project, project_id, "Proje")
    query = select(ProjectChangeOrder).where(
        ProjectChangeOrder.project_id == project.id, ProjectChangeOrder.status == RecordStatus.ACTIVE
    )
    if state:
        query = query.where(ProjectChangeOrder.change_state == state)
    orders = list(session.scalars(query.order_by(ProjectChangeOrder.created_at, ProjectChangeOrder.id)))
    approved = approved_change_total(session, project.id)
    return {
        "project_id": project.id,
        "contract_amount_kurus": project.contract_amount_kurus,
        "approved_total_kurus": approved,
        "pending_total_kurus": sum(o.amount_kurus for o in orders if o.change_state == "draft"),
        "revised_contract_kurus": revised_contract(project, approved),
        "change_orders": [ChangeOrderRead.model_validate(o) for o in orders],
    }


@router.patch("/projects/{project_id}/change-orders/{order_id}", response_model=ChangeOrderRead)
def update_change_order(
    project_id: str,
    order_id: str,
    payload: ChangeOrderUpdate,
    session: Session = Depends(get_session),
):
    require_active(session, Project, project_id, "Proje")
    order = _change_order(session, project_id, order_id)
    if order.change_state != "draft":
        raise ApiError(
            "change_order_locked", "Yalnız taslak ek iş düzenlenebilir.", 409,
            {"change_state": order.change_state},
        )
    changes = payload.model_dump(exclude_unset=True)
    before = {key: getattr(order, key) for key in changes}
    for key, value in changes.items():
        setattr(order, key, value)
    add_audit(session, "project_change_order", order.id, "updated", {"before": before, "after": changes})
    session.commit()
    session.refresh(order)
    return order


def _decide(target: str):
    def handler(
        project_id: str,
        order_id: str,
        payload: ChangeOrderDecision | None = None,
        session: Session = Depends(get_session),
    ):
        require_active(session, Project, project_id, "Proje")
        order = _change_order(session, project_id, order_id)
        return _transition(session, order, target, payload.note if payload else None)

    return handler


for _target, _path in (
    ("approved", "approve"),
    ("rejected", "reject"),
    ("cancelled", "cancel"),
):
    router.add_api_route(
        f"/projects/{{project_id}}/change-orders/{{order_id}}/{_path}",
        _decide(_target),
        methods=["POST"],
        response_model=ChangeOrderRead,
    )


# --- Satın alma yaşam döngüsü -----------------------------------------------------------------------


class PurchaseLifecycleRequest(BaseModel):
    state: Literal["ordered", "partially_received", "received", "cancelled"]
    received_kurus: int | None = Field(default=None, gt=0)
    # Teslim fişi tarihi; verilmezse sunucunun iş tarihi (istemci her zaman açıkça göndermelidir).
    receipt_date: date | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_request(self) -> PurchaseLifecycleRequest:
        if self.state == "partially_received" and self.received_kurus is None:
            raise ValueError("Kısmi teslimde teslim alınan tutar (received_kurus) zorunludur.")
        if self.state != "partially_received" and self.received_kurus is not None:
            raise ValueError("received_kurus yalnız kısmi teslimde gönderilir.")
        return self


class PurchaseLifecycleRead(OrmModel):
    id: str
    lifecycle_state: str
    total_kurus: int
    received_kurus: int
    status: RecordStatus
    warnings: list[dict] = Field(default_factory=list)


@router.post("/purchases/{purchase_id}/lifecycle", response_model=PurchaseLifecycleRead)
def set_purchase_lifecycle(
    purchase_id: str, payload: PurchaseLifecycleRequest, session: Session = Depends(get_session)
):
    """Durum geçişi. Teslim geçişleri (`partially_received`, `received`) teslim fişi yazar."""
    purchase = require_active(session, Purchase, purchase_id, "Satın alma")
    current = purchase.lifecycle_state
    if payload.state not in PURCHASE_TRANSITIONS[current]:
        raise ApiError(
            "invalid_transition",
            f"Satın alma '{current}' durumundan '{payload.state}' durumuna geçirilemez.",
            409,
            {"from": current, "to": payload.state},
        )
    if payload.state == "cancelled":
        return cancel_purchase(purchase_id, session)
    if payload.state == "ordered":
        purchase.lifecycle_state = "ordered"
    else:
        received = purchase.received_kurus
        if payload.state == "partially_received":
            assert payload.received_kurus is not None
            if payload.received_kurus >= purchase.total_kurus:
                raise ApiError(
                    "invalid_received_amount",
                    "Kısmi teslim tutarı toplamdan küçük olmalıdır; tam teslim için 'received' kullanın.",
                    422,
                    {"total_kurus": purchase.total_kurus},
                )
            if payload.received_kurus <= received:
                raise ApiError(
                    "invalid_received_amount",
                    "Teslim alınan tutar önceki teslimden büyük olmalıdır.",
                    422,
                    {"received_kurus": received},
                )
            delta, quantity = payload.received_kurus - received, None
        else:
            delta, quantity = purchase.total_kurus - received, None
            if purchase.quantity is not None:
                taken = session.scalar(
                    select(func.coalesce(func.sum(PurchaseReceipt.quantity), 0)).where(
                        PurchaseReceipt.purchase_id == purchase.id,
                        PurchaseReceipt.status == RecordStatus.ACTIVE,
                    )
                )
                rest = purchase.quantity - (taken or 0)
                quantity = rest if rest > 0 else None
        count = session.scalar(
            select(func.count(PurchaseReceipt.id)).where(PurchaseReceipt.purchase_id == purchase.id)
        )
        add_receipt(
            session,
            purchase,
            receipt_date=payload.receipt_date or clock.business_today(),
            amount_kurus=delta,
            quantity=quantity,
            note=payload.note,
            idempotency_key=payload.idempotency_key or f"lifecycle:{purchase.id}:{count}",
        )
    add_audit(
        session,
        "purchase",
        purchase.id,
        "lifecycle",
        {"from": current, "to": purchase.lifecycle_state, "received_kurus": purchase.received_kurus,
         "note": payload.note},
    )
    session.commit()
    session.refresh(purchase)
    read = PurchaseLifecycleRead.model_validate(purchase)
    read.warnings = quantity_warnings(session, purchase)
    return read


# --- Maliyet kaynakları -----------------------------------------------------------------------------


def collect_cost_sources(session: Session, project: Project) -> dict[str, dict[str, list[dict]]]:
    """Kategori -> {'actual': [...], 'commitment': [...]}; her kalem kaynak kayıt kimliğini taşır."""
    sources: dict[str, dict[str, list[dict]]] = {
        category: {"actual": [], "commitment": []} for category in BUDGET_CATEGORIES
    }
    not_opening = ~Purchase.idempotency_key.like(f"{OPENING_PREFIX}%")
    receipts = session.execute(
        select(PurchaseReceipt, Purchase, Material.name)
        .join(Purchase, Purchase.id == PurchaseReceipt.purchase_id)
        .join(Material, Material.id == Purchase.material_id)
        .where(
            Purchase.project_id == project.id,
            Purchase.status == RecordStatus.ACTIVE,
            PurchaseReceipt.status == RecordStatus.ACTIVE,
            not_opening,
        )
        .order_by(PurchaseReceipt.receipt_date, PurchaseReceipt.id)
    ).all()
    for receipt, purchase, material_name in receipts:
        sources["material"]["actual"].append(
            {
                "source_type": "purchase_receipt",
                "source_id": receipt.id,
                "purchase_id": purchase.id,
                "date": receipt.receipt_date,
                "amount_kurus": receipt.amount_kurus,
                "label": material_name,
                "lifecycle_state": purchase.lifecycle_state,
            }
        )
    committing = session.execute(
        select(Purchase, Material.name)
        .join(Material, Material.id == Purchase.material_id)
        .where(
            Purchase.project_id == project.id,
            Purchase.status == RecordStatus.ACTIVE,
            Purchase.lifecycle_state.in_(COMMITTING_STATES),
            not_opening,
        )
        .order_by(Purchase.purchase_date, Purchase.id)
    ).all()
    for purchase, material_name in committing:
        outstanding = purchase.total_kurus - purchase.received_kurus
        if outstanding > 0:
            sources["material"]["commitment"].append(
                {
                    "source_type": "purchase",
                    "source_id": purchase.id,
                    "purchase_id": purchase.id,
                    "date": purchase.purchase_date,
                    "amount_kurus": outstanding,
                    "label": material_name,
                    "lifecycle_state": purchase.lifecycle_state,
                }
            )
    for log in session.scalars(
        select(WorkLog)
        .where(WorkLog.project_id == project.id, WorkLog.status == RecordStatus.ACTIVE)
        .order_by(WorkLog.work_date, WorkLog.id)
    ):
        sources["labor"]["actual"].append(
            {
                "source_type": "work_log",
                "source_id": log.id,
                "date": log.work_date,
                "amount_kurus": log.amount_kurus,
                "label": log.work_status,
                "employee_id": log.employee_id,
            }
        )
    for expense in session.scalars(
        select(ProjectExpense)
        .where(ProjectExpense.project_id == project.id, ProjectExpense.status == RecordStatus.ACTIVE)
        .order_by(ProjectExpense.expense_date, ProjectExpense.id)
    ):
        sources[EXPENSE_TO_BUDGET[expense.category]]["actual"].append(
            {
                "source_type": "project_expense",
                "source_id": expense.id,
                "date": expense.expense_date,
                "amount_kurus": expense.amount_kurus,
                "label": expense.description,
            }
        )
    return sources


def _total(items: list[dict]) -> int:
    return sum(item["amount_kurus"] for item in items)


# --- Manuel kalan maliyet tahmini -------------------------------------------------------------------


class ForecastItem(BaseModel):
    category: BudgetCategory
    # None: manuel tahmini kaldır, otomatik artık hesabına dön.
    remaining_estimate_kurus: int | None = Field(default=None, ge=0)
    as_of_date: date
    reason: str = Field(min_length=3, max_length=255)


class ForecastUpdate(BaseModel):
    items: list[ForecastItem] = Field(min_length=1, max_length=len(BUDGET_CATEGORIES))

    @model_validator(mode="after")
    def unique_categories(self) -> ForecastUpdate:
        names = [item.category for item in self.items]
        if len(names) != len(set(names)):
            raise ValueError("Aynı kategori bir istekte yalnız bir kez gönderilebilir.")
        return self


def manual_forecasts(session: Session, project_id: str) -> dict[str, ProjectCostForecast]:
    """Kategori başına güncel (ACTIVE) revizyon; yalnız tahmin değeri olanlar manueldir."""
    rows = session.scalars(
        select(ProjectCostForecast).where(
            ProjectCostForecast.project_id == project_id,
            ProjectCostForecast.status == RecordStatus.ACTIVE,
        )
    )
    return {r.category: r for r in rows}


def build_categories(
    session: Session, project: Project, sources: dict, lines: list[ProjectBudgetLine]
) -> list[dict]:
    manual = manual_forecasts(session, project.id)
    rows = []
    for category in BUDGET_CATEGORIES:
        category_lines = [line for line in lines if line.category == category]
        actual = _total(sources[category]["actual"])
        commitment = _total(sources[category]["commitment"])
        budget = sum(line.amount_kurus for line in category_lines) if category_lines else None
        auto = max(budget - actual - commitment, 0) if budget is not None else 0
        chosen = manual.get(category)
        is_manual = chosen is not None and chosen.remaining_estimate_kurus is not None
        remaining = chosen.remaining_estimate_kurus if is_manual else auto
        forecast = actual + commitment + remaining
        rows.append(
            {
                "category": category,
                "budget_kurus": budget,
                "original_budget_kurus": (
                    sum(line.original_amount_kurus for line in category_lines)
                    if category_lines
                    else None
                ),
                "actual_kurus": actual,
                "commitment_kurus": commitment,
                "auto_remaining_estimate_kurus": auto,
                "remaining_estimate_kurus": remaining,
                "forecast_source": "manual" if is_manual else "auto",
                "forecast_revision_no": chosen.revision_no if is_manual else None,
                "forecast_as_of_date": chosen.as_of_date if is_manual else None,
                "forecast_reason": chosen.reason if is_manual else None,
                "forecast_kurus": forecast,
                "variance_kurus": (budget - forecast) if budget is not None else None,
                "budget_line_ids": [line.id for line in category_lines],
            }
        )
    return rows


def _active_lines(session: Session, project_id: str) -> list[ProjectBudgetLine]:
    return list(
        session.scalars(
            select(ProjectBudgetLine).where(
                ProjectBudgetLine.project_id == project_id,
                ProjectBudgetLine.status == RecordStatus.ACTIVE,
            )
        )
    )


def _forecast_view(session: Session, project: Project) -> list[dict]:
    categories = build_categories(
        session, project, collect_cost_sources(session, project), _active_lines(session, project.id)
    )
    return [
        {
            "category": row["category"],
            "forecast_source": row["forecast_source"],
            "remaining_estimate_kurus": row["remaining_estimate_kurus"],
            "auto_remaining_estimate_kurus": row["auto_remaining_estimate_kurus"],
            "revision_no": row["forecast_revision_no"],
            "as_of_date": row["forecast_as_of_date"],
            "reason": row["forecast_reason"],
        }
        for row in categories
    ]


@router.get("/projects/{project_id}/cost-forecasts")
def get_cost_forecasts(project_id: str, session: Session = Depends(get_session)):
    project = require_active(session, Project, project_id, "Proje")
    return {"project_id": project.id, "forecasts": _forecast_view(session, project)}


@router.get("/projects/{project_id}/cost-forecasts/history")
def get_cost_forecast_history(
    project_id: str, category: BudgetCategory | None = None, session: Session = Depends(get_session)
):
    project = require_active(session, Project, project_id, "Proje")
    query = select(ProjectCostForecast).where(ProjectCostForecast.project_id == project.id)
    if category:
        query = query.where(ProjectCostForecast.category == category)
    rows = session.scalars(
        query.order_by(ProjectCostForecast.category, ProjectCostForecast.revision_no)
    )
    return {
        "project_id": project.id,
        "revisions": [
            {
                "id": r.id,
                "category": r.category,
                "revision_no": r.revision_no,
                "remaining_estimate_kurus": r.remaining_estimate_kurus,
                "forecast_source": "manual" if r.remaining_estimate_kurus is not None else "auto",
                "as_of_date": r.as_of_date,
                "reason": r.reason,
                "is_current": r.status == RecordStatus.ACTIVE,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


@router.put("/projects/{project_id}/cost-forecasts")
def put_cost_forecasts(
    project_id: str, payload: ForecastUpdate, session: Session = Depends(get_session)
):
    project = require_active(session, Project, project_id, "Proje")
    current = manual_forecasts(session, project.id)
    for item in payload.items:
        previous = current.get(item.category)
        if item.remaining_estimate_kurus is None and (
            previous is None or previous.remaining_estimate_kurus is None
        ):
            raise ApiError(
                "no_manual_forecast",
                "Kaldırılacak manuel tahmin yok.",
                409,
                {"category": item.category},
            )
        last_revision = session.scalar(
            select(func.max(ProjectCostForecast.revision_no)).where(
                ProjectCostForecast.project_id == project.id,
                ProjectCostForecast.category == item.category,
            )
        )
        if previous is not None:
            previous.status = RecordStatus.ARCHIVED
            session.flush()
        revision = ProjectCostForecast(
            project_id=project.id,
            category=item.category,
            revision_no=(last_revision or 0) + 1,
            remaining_estimate_kurus=item.remaining_estimate_kurus,
            as_of_date=item.as_of_date,
            reason=item.reason,
        )
        session.add(revision)
        session.flush()
        add_audit(
            session,
            "project_cost_forecast",
            revision.id,
            "revised",
            {
                "project_id": project.id,
                "category": item.category,
                "previous_kurus": previous.remaining_estimate_kurus if previous else None,
                "remaining_estimate_kurus": item.remaining_estimate_kurus,
                "reason": item.reason,
            },
        )
    session.commit()
    return {"project_id": project.id, "forecasts": _forecast_view(session, project)}


# --- Kârlılık ve maliyet detayı ---------------------------------------------------------------------


@router.get("/projects/{project_id}/profitability")
def project_profitability(project_id: str, session: Session = Depends(get_session)):
    project = require_active(session, Project, project_id, "Proje")
    return compute_profitability(session, project)


def compute_profitability(session: Session, project: Project) -> dict:
    """Kârlılık hesabı (uç nokta, rapor, ML ve tasarruf analizi ortak kullanır)."""
    sources = collect_cost_sources(session, project)
    lines = _active_lines(session, project.id)
    approved = approved_change_total(session, project.id)
    revised = revised_contract(project, approved)
    pending = int(
        session.scalar(
            select(func.coalesce(func.sum(ProjectChangeOrder.amount_kurus), 0)).where(
                ProjectChangeOrder.project_id == project.id,
                ProjectChangeOrder.change_state == "draft",
                ProjectChangeOrder.status == RecordStatus.ACTIVE,
            )
        )
        or 0
    )

    if lines:
        budget_source = "budget_lines"
        original_budget = sum(line.original_amount_kurus for line in lines)
        revised_budget = sum(line.amount_kurus for line in lines)
    elif project.budget_kurus is not None:
        budget_source = "project_budget"
        original_budget = revised_budget = project.budget_kurus
    else:
        budget_source = "none"
        original_budget = revised_budget = None

    categories = build_categories(session, project, sources, lines)
    actual_total = sum(c["actual_kurus"] for c in categories)
    commitment_total = sum(c["commitment_kurus"] for c in categories)
    remaining_total = sum(c["remaining_estimate_kurus"] for c in categories)
    manual_count = sum(1 for c in categories if c["forecast_source"] == "manual")

    unallocated_remaining = 0
    if budget_source == "project_budget":
        # Satır bazlı bütçe yoksa proje geneli bütçeden kalan tek kalemde tahmin edilir; manuel
        # tahminler bu bütçeden harcanmış sayılır.
        unallocated_remaining = max(
            project.budget_kurus - actual_total - commitment_total - remaining_total, 0
        )
    forecast_total = actual_total + commitment_total + remaining_total + unallocated_remaining
    profit = revised - forecast_total if revised is not None else None
    return {
        "project_id": project.id,
        "contract_amount_kurus": project.contract_amount_kurus,
        "approved_change_orders_kurus": approved,
        "pending_change_orders_kurus": pending,
        "revised_contract_kurus": revised,
        "budget_source": budget_source,
        "original_budget_kurus": original_budget,
        "revised_budget_kurus": revised_budget,
        "actual_cost_kurus": actual_total,
        "commitment_kurus": commitment_total,
        "remaining_estimate_kurus": remaining_total + unallocated_remaining,
        "manual_forecast_count": manual_count,
        "forecast_cost_at_completion_kurus": forecast_total,
        "budget_variance_kurus": (
            revised_budget - forecast_total if revised_budget is not None else None
        ),
        "current_profit_kurus": (revised - actual_total) if revised is not None else None,
        "estimated_profit_kurus": profit,
        "estimated_margin_percent": (
            round(profit / revised * 100, 2) if profit is not None and revised else None
        ),
        "categories": categories,
        **project_collection_summary(session, project),
    }


@router.get("/projects/{project_id}/cost-drilldown")
def project_cost_drilldown(
    project_id: str,
    category: BudgetCategory | None = None,
    limit: int = Query(5000, ge=1, le=20000),
    session: Session = Depends(get_session),
):
    project = require_active(session, Project, project_id, "Proje")
    sources = collect_cost_sources(session, project)
    forecasts = {
        row["category"]: row
        for row in build_categories(session, project, sources, _active_lines(session, project.id))
    }
    result = []
    actual_total = commitment_total = 0
    for name in BUDGET_CATEGORIES:
        if category is not None and name != category:
            continue
        actual_items = sources[name]["actual"]
        commitment_items = sources[name]["commitment"]
        actual, commitment = _total(actual_items), _total(commitment_items)
        actual_total += actual
        commitment_total += commitment
        result.append(
            {
                "category": name,
                "actual_kurus": actual,
                "commitment_kurus": commitment,
                "remaining_estimate_kurus": forecasts[name]["remaining_estimate_kurus"],
                "forecast_source": forecasts[name]["forecast_source"],
                "forecast_kurus": forecasts[name]["forecast_kurus"],
                "actual_source_count": len(actual_items),
                "commitment_source_count": len(commitment_items),
                "actual_sources": actual_items[:limit],
                "commitment_sources": commitment_items[:limit],
                "truncated": len(actual_items) > limit or len(commitment_items) > limit,
            }
        )
    return {
        "project_id": project.id,
        "as_of_note": "Toplamlar mevcut kayıt durumunu yansıtır; her kalem kaynak kimliği taşır.",
        "actual_total_kurus": actual_total,
        "commitment_total_kurus": commitment_total,
        "categories": result,
    }

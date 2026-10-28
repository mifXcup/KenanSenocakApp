from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import clock
from .backup import BackupError, backup_manager
from .config import get_settings
from .database import get_session
from .models import (
    AuditLog,
    Material,
    MaterialMovement,
    MovementType,
    Payment,
    Project,
    ProjectColor,
    ProjectMeasurement,
    ProjectNote,
    ProjectTask,
    ProjectVisit,
    Purchase,
    RecordStatus,
    Supplier,
    TrackingMode,
)
from .reports import debt_aging, purchase_report
from .schemas import (
    BackupRead,
    BackupRestoreResult,
    BackupStatus,
    DashboardSummary,
    DebtAgingReport,
    MaterialBalance,
    MaterialCreate,
    MaterialRead,
    MaterialUpdate,
    MovementCreate,
    MovementRead,
    PaymentCreate,
    PaymentRead,
    ProjectColorCreate,
    ProjectColorRead,
    ProjectCreate,
    ProjectHubRead,
    ProjectMeasurementCreate,
    ProjectMeasurementRead,
    ProjectNoteCreate,
    ProjectNoteRead,
    ProjectRead,
    ProjectTaskCreate,
    ProjectTaskRead,
    ProjectTaskUpdate,
    ProjectUpdate,
    ProjectVisitCreate,
    ProjectVisitRead,
    PurchaseCreate,
    PurchaseDetail,
    PurchaseRead,
    PurchaseReport,
    PurchaseUpdate,
    SupplierBalance,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
)

router = APIRouter(prefix="/api/v1")


class ApiError(Exception):
    def __init__(
        self, code: str, message: str, http_status: int = 400, details: object | None = None
    ):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details


def error_payload(code: str, message: str, details: object | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=jsonable_encoder(error_payload(exc.code, exc.message, exc.details)),
    )


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_payload(
            "validation_error",
            "Girilen bilgiler geçerli değil.",
            [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()],
        ),
    )


def require_sidecar_token(x_ks_sidecar_token: str | None = Header(default=None)) -> None:
    expected = get_settings().sidecar_token
    if expected and x_ks_sidecar_token != expected:
        raise ApiError("unauthorized", "Geçersiz masaüstü istemcisi.", 401)


def run_backup_operation(operation):
    try:
        return operation()
    except BackupError as exc:
        http_status = 404 if exc.code == "backup_not_found" else 409
        raise ApiError(exc.code, exc.message, http_status, exc.details) from exc


def require_active(session: Session, model, entity_id: str, label: str):
    entity = session.get(model, entity_id)
    if entity is None or entity.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", f"{label} bulunamadı.", 404)
    return entity


def add_audit(
    session: Session, entity_type: str, entity_id: str, action: str, detail: dict | None = None
) -> None:
    session.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            detail=json.dumps(jsonable_encoder(detail), ensure_ascii=False) if detail else None,
        )
    )


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "ks-yonetim-core"}


@router.get(
    "/backups/status",
    response_model=BackupStatus,
    dependencies=[Depends(require_sidecar_token)],
)
def backup_status() -> dict:
    return backup_manager.status()


@router.get(
    "/backups",
    response_model=list[BackupRead],
    dependencies=[Depends(require_sidecar_token)],
)
def list_backups():
    return backup_manager.list()


@router.post(
    "/backups",
    response_model=BackupRead,
    status_code=201,
    dependencies=[Depends(require_sidecar_token)],
)
def create_backup():
    return run_backup_operation(lambda: backup_manager.create("manual"))


@router.post(
    "/backups/{backup_id}/verify",
    response_model=BackupRead,
    dependencies=[Depends(require_sidecar_token)],
)
def verify_backup(backup_id: str):
    return run_backup_operation(lambda: backup_manager.verify(backup_id))


@router.post(
    "/backups/{backup_id}/restore",
    response_model=BackupRestoreResult,
    dependencies=[Depends(require_sidecar_token)],
)
def restore_backup(backup_id: str) -> BackupRestoreResult:
    selected, pre_restore = run_backup_operation(lambda: backup_manager.restore(backup_id))
    return BackupRestoreResult(
        restored_backup=BackupRead.model_validate(selected, from_attributes=True),
        pre_restore_backup=BackupRead.model_validate(pre_restore, from_attributes=True),
        restart_required=True,
    )


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummary,
    dependencies=[Depends(require_sidecar_token)],
)
def dashboard_summary(session: Session = Depends(get_session)) -> DashboardSummary:
    active_project_count = int(
        session.scalar(select(func.count(Project.id)).where(Project.status == RecordStatus.ACTIVE))
        or 0
    )
    supplier_count = int(
        session.scalar(
            select(func.count(Supplier.id)).where(Supplier.status == RecordStatus.ACTIVE)
        )
        or 0
    )
    purchase_total = int(
        session.scalar(
            select(func.coalesce(func.sum(Purchase.received_kurus), 0)).where(
                Purchase.status == RecordStatus.ACTIVE
            )
        )
        or 0
    )
    payment_total = int(
        session.scalar(
            select(func.coalesce(func.sum(Payment.amount_kurus), 0)).where(
                Payment.status == RecordStatus.ACTIVE
            )
        )
        or 0
    )
    return DashboardSummary(
        active_project_count=active_project_count,
        supplier_count=supplier_count,
        purchase_total_kurus=purchase_total,
        payment_total_kurus=payment_total,
        supplier_debt_kurus=purchase_total - payment_total,
    )


@router.get(
    "/reports/purchases",
    response_model=PurchaseReport,
    dependencies=[Depends(require_sidecar_token)],
)
def purchases_report(
    session: Session = Depends(get_session),
    date_from: date | None = None,
    date_to: date | None = None,
    supplier_id: str | None = None,
    project_id: str | None = None,
) -> PurchaseReport:
    if date_from and date_to and date_from > date_to:
        raise ApiError("invalid_range", "Başlangıç tarihi bitiş tarihinden sonra olamaz.", 422)
    return purchase_report(session, date_from, date_to, supplier_id, project_id)


@router.get(
    "/reports/debt-aging",
    response_model=DebtAgingReport,
    dependencies=[Depends(require_sidecar_token)],
)
def debt_aging_report(
    session: Session = Depends(get_session), as_of: date | None = None
) -> DebtAgingReport:
    return debt_aging(session, as_of or clock.business_today())


@router.post(
    "/suppliers",
    response_model=SupplierRead,
    status_code=201,
    dependencies=[Depends(require_sidecar_token)],
)
def create_supplier(payload: SupplierCreate, session: Session = Depends(get_session)) -> Supplier:
    supplier = Supplier(**payload.model_dump())
    session.add(supplier)
    session.flush()
    add_audit(session, "supplier", supplier.id, "created")
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("duplicate_supplier", "Bu firma zaten kayıtlı.", 409) from exc
    session.refresh(supplier)
    return supplier


@router.patch(
    "/suppliers/{supplier_id}",
    response_model=SupplierRead,
    dependencies=[Depends(require_sidecar_token)],
)
def update_supplier(
    supplier_id: str, payload: SupplierUpdate, session: Session = Depends(get_session)
) -> Supplier:
    supplier = require_active(session, Supplier, supplier_id, "Firma")
    changes = payload.model_dump(exclude_unset=True)
    before = {key: getattr(supplier, key) for key in changes}
    for key, value in changes.items():
        setattr(supplier, key, value)
    add_audit(session, "supplier", supplier.id, "updated", {"before": before, "after": changes})
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("duplicate_supplier", "Bu firma adı zaten kullanılıyor.", 409) from exc
    session.refresh(supplier)
    return supplier


@router.get(
    "/suppliers", response_model=list[SupplierRead], dependencies=[Depends(require_sidecar_token)]
)
def list_suppliers(
    session: Session = Depends(get_session),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return session.scalars(
        select(Supplier)
        .where(Supplier.status == RecordStatus.ACTIVE)
        .order_by(Supplier.name)
        .limit(limit)
        .offset(offset)
    ).all()


@router.post(
    "/materials",
    response_model=MaterialRead,
    status_code=201,
    dependencies=[Depends(require_sidecar_token)],
)
def create_material(payload: MaterialCreate, session: Session = Depends(get_session)) -> Material:
    material = Material(**payload.model_dump())
    session.add(material)
    session.flush()
    add_audit(session, "material", material.id, "created")
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("duplicate_material", "Bu malzeme zaten kayıtlı.", 409) from exc
    session.refresh(material)
    return material


@router.patch(
    "/materials/{material_id}",
    response_model=MaterialRead,
    dependencies=[Depends(require_sidecar_token)],
)
def update_material(
    material_id: str, payload: MaterialUpdate, session: Session = Depends(get_session)
) -> Material:
    material = require_active(session, Material, material_id, "Malzeme")
    changes = payload.model_dump(exclude_unset=True)
    before = {key: getattr(material, key) for key in changes}
    for key, value in changes.items():
        setattr(material, key, value)
    add_audit(session, "material", material.id, "updated", {"before": before, "after": changes})
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError("duplicate_material", "Bu malzeme adı zaten kullanılıyor.", 409) from exc
    session.refresh(material)
    return material


@router.get(
    "/materials", response_model=list[MaterialRead], dependencies=[Depends(require_sidecar_token)]
)
def list_materials(
    session: Session = Depends(get_session),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return session.scalars(
        select(Material)
        .where(Material.status == RecordStatus.ACTIVE)
        .order_by(Material.name)
        .limit(limit)
        .offset(offset)
    ).all()


@router.post(
    "/projects",
    response_model=ProjectRead,
    status_code=201,
    dependencies=[Depends(require_sidecar_token)],
)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    from .customers import find_or_create_customer, get_customer

    data = payload.model_dump(exclude={"customer_id"})
    if payload.customer_id:
        customer = get_customer(session, payload.customer_id)
        data["customer_name"] = customer.name
    else:
        customer = find_or_create_customer(session, payload.customer_name)
    project = Project(**data, customer_id=customer.id)
    session.add(project)
    session.flush()
    add_audit(session, "project", project.id, "created")
    session.commit()
    session.refresh(project)
    return project


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectRead,
    dependencies=[Depends(require_sidecar_token)],
)
def update_project(
    project_id: str, payload: ProjectUpdate, session: Session = Depends(get_session)
) -> Project:
    from .customers import find_or_create_customer, get_customer

    project = require_active(session, Project, project_id, "Proje")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("customer_id"):
        customer = get_customer(session, changes["customer_id"])
        changes["customer_name"] = customer.name
    elif "customer_name" in changes:
        customer = find_or_create_customer(session, changes["customer_name"])
        changes["customer_id"] = customer.id
    else:
        changes.pop("customer_id", None)
    before = {key: getattr(project, key) for key in changes}
    for key, value in changes.items():
        setattr(project, key, value)
    add_audit(session, "project", project.id, "updated", {"before": before, "after": changes})
    session.commit()
    session.refresh(project)
    return project


@router.get(
    "/projects", response_model=list[ProjectRead], dependencies=[Depends(require_sidecar_token)]
)
def list_projects(
    session: Session = Depends(get_session),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return session.scalars(
        select(Project)
        .where(Project.status == RecordStatus.ACTIVE)
        .order_by(Project.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.get(
    "/projects/{project_id}/hub",
    response_model=ProjectHubRead,
    dependencies=[Depends(require_sidecar_token)],
)
def get_project_hub(project_id: str, session: Session = Depends(get_session)):
    project = require_active(session, Project, project_id, "Proje")

    def active_rows(model, order_by):
        return session.scalars(
            select(model)
            .where(model.project_id == project_id, model.status == RecordStatus.ACTIVE)
            .order_by(order_by)
        ).all()

    return {
        "project": project,
        "notes": active_rows(ProjectNote, ProjectNote.created_at.desc()),
        "tasks": active_rows(ProjectTask, ProjectTask.created_at.desc()),
        "colors": active_rows(ProjectColor, ProjectColor.created_at.desc()),
        "measurements": active_rows(ProjectMeasurement, ProjectMeasurement.measured_on.desc()),
        "visits": active_rows(ProjectVisit, ProjectVisit.visit_date.asc()),
    }


def add_project_child(session: Session, project_id: str, model, payload, label: str):
    require_active(session, Project, project_id, "Proje")
    entity = model(project_id=project_id, **payload.model_dump())
    session.add(entity)
    session.flush()
    add_audit(session, model.__tablename__, entity.id, "created", {"project_id": project_id})
    session.commit()
    session.refresh(entity)
    return entity


@router.post("/projects/{project_id}/notes", response_model=ProjectNoteRead, status_code=201, dependencies=[Depends(require_sidecar_token)])
def create_project_note(project_id: str, payload: ProjectNoteCreate, session: Session = Depends(get_session)):
    return add_project_child(session, project_id, ProjectNote, payload, "Not")


@router.post("/projects/{project_id}/tasks", response_model=ProjectTaskRead, status_code=201, dependencies=[Depends(require_sidecar_token)])
def create_project_task(project_id: str, payload: ProjectTaskCreate, session: Session = Depends(get_session)):
    return add_project_child(session, project_id, ProjectTask, payload, "İş")


@router.patch("/project-tasks/{task_id}", response_model=ProjectTaskRead, dependencies=[Depends(require_sidecar_token)])
def update_project_task(task_id: str, payload: ProjectTaskUpdate, session: Session = Depends(get_session)):
    task = require_active(session, ProjectTask, task_id, "İş")
    before = task.task_state
    task.task_state = payload.task_state
    add_audit(session, "project_tasks", task.id, "updated", {"before": before, "after": payload.task_state})
    session.commit()
    session.refresh(task)
    return task


@router.post("/projects/{project_id}/colors", response_model=ProjectColorRead, status_code=201, dependencies=[Depends(require_sidecar_token)])
def create_project_color(project_id: str, payload: ProjectColorCreate, session: Session = Depends(get_session)):
    return add_project_child(session, project_id, ProjectColor, payload, "Renk")


@router.post("/projects/{project_id}/measurements", response_model=ProjectMeasurementRead, status_code=201, dependencies=[Depends(require_sidecar_token)])
def create_project_measurement(project_id: str, payload: ProjectMeasurementCreate, session: Session = Depends(get_session)):
    return add_project_child(session, project_id, ProjectMeasurement, payload, "Ölçü")


@router.post("/projects/{project_id}/visits", response_model=ProjectVisitRead, status_code=201, dependencies=[Depends(require_sidecar_token)])
def create_project_visit(project_id: str, payload: ProjectVisitCreate, session: Session = Depends(get_session)):
    return add_project_child(session, project_id, ProjectVisit, payload, "Ziyaret")


def purchase_paid(session: Session, purchase_id: str) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(Payment.amount_kurus), 0)).where(
                Payment.purchase_id == purchase_id, Payment.status == RecordStatus.ACTIVE
            )
        )
        or 0
    )


def to_purchase_detail(purchase: Purchase, paid_kurus: int) -> PurchaseDetail:
    return PurchaseDetail(
        **PurchaseRead.model_validate(purchase).model_dump(),
        paid_kurus=paid_kurus,
        remaining_kurus=purchase.total_kurus - paid_kurus,
    )


@router.post(
    "/purchases",
    response_model=PurchaseDetail,
    status_code=201,
    dependencies=[Depends(require_sidecar_token)],
)
def create_purchase(
    payload: PurchaseCreate, session: Session = Depends(get_session)
) -> PurchaseDetail:
    existing = session.scalar(
        select(Purchase).where(Purchase.idempotency_key == payload.idempotency_key)
    )
    if existing:
        paid = purchase_paid(session, existing.id)
        return to_purchase_detail(existing, paid)
    supplier = require_active(session, Supplier, payload.supplier_id, "Firma")
    require_active(session, Material, payload.material_id, "Malzeme")
    if payload.project_id:
        require_active(session, Project, payload.project_id, "Proje")
    purchase_data = payload.model_dump(exclude={"paid_kurus", "total_kurus"})
    total = payload.resolved_total_kurus
    received = payload.lifecycle_state == "received"
    purchase = Purchase(**purchase_data, total_kurus=total, received_kurus=0)
    session.add(purchase)
    session.flush()
    if received:
        from .receipts import add_receipt

        add_receipt(
            session,
            purchase,
            receipt_date=payload.purchase_date,
            amount_kurus=total,
            quantity=payload.quantity,
            idempotency_key=f"{payload.idempotency_key}:receipt",
        )
    if payload.paid_kurus:
        session.add(
            Payment(
                supplier_id=supplier.id,
                purchase_id=purchase.id,
                payment_date=payload.purchase_date,
                amount_kurus=payload.paid_kurus,
                note="Satın alma sırasında yapılan ilk ödeme",
                idempotency_key=f"{payload.idempotency_key}:initial-payment",
            )
        )
    add_audit(session, "purchase", purchase.id, "created", {"total_kurus": purchase.total_kurus})
    session.commit()
    session.refresh(purchase)
    return to_purchase_detail(purchase, payload.paid_kurus)


@router.patch(
    "/purchases/{purchase_id}",
    response_model=PurchaseDetail,
    dependencies=[Depends(require_sidecar_token)],
)
def update_purchase(
    purchase_id: str, payload: PurchaseUpdate, session: Session = Depends(get_session)
) -> PurchaseDetail:
    purchase = require_active(session, Purchase, purchase_id, "Satın alma")
    changes = payload.model_dump(exclude_unset=True)
    if "due_date" in changes:
        due_date = changes["due_date"]
        if due_date is not None and due_date < purchase.purchase_date:
            raise ApiError(
                "invalid_due_date",
                "Vade tarihi satın alma tarihinden önce olamaz.",
                422,
            )
    if "project_id" in changes and changes["project_id"] is not None:
        require_active(session, Project, changes["project_id"], "Proje")

    before = {key: getattr(purchase, key) for key in changes}
    for key, value in changes.items():
        setattr(purchase, key, value)
    if "project_id" in changes:
        movements = session.scalars(
            select(MaterialMovement).where(
                MaterialMovement.purchase_id == purchase.id,
                MaterialMovement.status == RecordStatus.ACTIVE,
            )
        ).all()
        for movement in movements:
            movement.project_id = changes["project_id"]

    add_audit(session, "purchase", purchase.id, "updated", {"before": before, "after": changes})
    session.commit()
    session.refresh(purchase)
    return to_purchase_detail(purchase, purchase_paid(session, purchase.id))


@router.get(
    "/purchases", response_model=list[PurchaseRead], dependencies=[Depends(require_sidecar_token)]
)
def list_purchases(
    session: Session = Depends(get_session),
    supplier_id: str | None = None,
    project_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(Purchase).where(Purchase.status == RecordStatus.ACTIVE)
    if supplier_id:
        query = query.where(Purchase.supplier_id == supplier_id)
    if project_id:
        query = query.where(Purchase.project_id == project_id)
    return session.scalars(
        query.order_by(Purchase.purchase_date.desc(), Purchase.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.post(
    "/payments",
    response_model=PaymentRead,
    status_code=201,
    dependencies=[Depends(require_sidecar_token)],
)
def create_payment(payload: PaymentCreate, session: Session = Depends(get_session)) -> Payment:
    existing = session.scalar(
        select(Payment).where(Payment.idempotency_key == payload.idempotency_key)
    )
    if existing:
        return existing
    require_active(session, Supplier, payload.supplier_id, "Firma")
    if payload.purchase_id:
        purchase = require_active(session, Purchase, payload.purchase_id, "Satın alma")
        if purchase.supplier_id != payload.supplier_id:
            raise ApiError(
                "supplier_mismatch", "Ödeme firması satın alma firmasıyla uyuşmuyor.", 409
            )
        remaining = purchase.total_kurus - purchase_paid(session, purchase.id)
        if payload.amount_kurus > remaining:
            raise ApiError(
                "overpayment",
                "Ödeme satın almanın kalan tutarını aşıyor.",
                409,
                {"remaining_kurus": remaining},
            )
    payment = Payment(**payload.model_dump())
    session.add(payment)
    session.flush()
    add_audit(session, "payment", payment.id, "created", {"amount_kurus": payment.amount_kurus})
    session.commit()
    session.refresh(payment)
    return payment


@router.get(
    "/payments", response_model=list[PaymentRead], dependencies=[Depends(require_sidecar_token)]
)
def list_payments(
    session: Session = Depends(get_session),
    supplier_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    query = select(Payment)
    if supplier_id:
        query = query.where(Payment.supplier_id == supplier_id)
    return session.scalars(
        query.order_by(Payment.payment_date.desc(), Payment.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.post(
    "/payments/{payment_id}/reverse",
    response_model=PaymentRead,
    dependencies=[Depends(require_sidecar_token)],
)
def reverse_payment(payment_id: str, session: Session = Depends(get_session)) -> Payment:
    payment = session.get(Payment, payment_id)
    if payment is None:
        raise ApiError("not_found", "Ödeme bulunamadı.", 404)
    if payment.status == RecordStatus.REVERSED:
        raise ApiError("already_reversed", "Bu ödeme zaten terslenmiş.", 409)
    if payment.status != RecordStatus.ACTIVE:
        raise ApiError("not_found", "Ödeme bulunamadı.", 404)
    payment.status = RecordStatus.REVERSED
    payment.reversed_at = datetime.now(UTC)
    add_audit(session, "payment", payment.id, "reversed")
    session.commit()
    session.refresh(payment)
    return payment


@router.post(
    "/purchases/{purchase_id}/cancel",
    response_model=PurchaseRead,
    dependencies=[Depends(require_sidecar_token)],
)
def cancel_purchase(purchase_id: str, session: Session = Depends(get_session)) -> Purchase:
    purchase = require_active(session, Purchase, purchase_id, "Satın alma")
    if purchase_paid(session, purchase.id):
        raise ApiError(
            "purchase_has_payments",
            "Ödemesi bulunan satın alma önce ödeme ters kaydı yapılmadan iptal edilemez.",
            409,
        )
    from .receipts import cancel_all_receipts

    cancel_all_receipts(session, purchase, "Satın alma iptali")
    purchase.status = RecordStatus.CANCELLED
    purchase.lifecycle_state = "cancelled"
    purchase.received_kurus = 0
    movements = session.scalars(
        select(MaterialMovement).where(
            MaterialMovement.purchase_id == purchase.id,
            MaterialMovement.status == RecordStatus.ACTIVE,
        )
    ).all()
    for movement in movements:
        movement.status = RecordStatus.CANCELLED
    add_audit(session, "purchase", purchase.id, "cancelled")
    session.commit()
    session.refresh(purchase)
    return purchase


@router.post(
    "/material-movements",
    response_model=MovementRead,
    status_code=201,
    dependencies=[Depends(require_sidecar_token)],
)
def create_movement(
    payload: MovementCreate, session: Session = Depends(get_session)
) -> MaterialMovement:
    material = require_active(session, Material, payload.material_id, "Malzeme")
    if payload.project_id:
        require_active(session, Project, payload.project_id, "Proje")
    movement = MaterialMovement(**payload.model_dump())
    if movement.unit is None:
        movement.unit = material.default_unit
    session.add(movement)
    session.flush()
    add_audit(session, "material_movement", movement.id, "created")
    session.commit()
    session.refresh(movement)
    return movement


@router.get(
    "/suppliers/{supplier_id}/balance",
    response_model=SupplierBalance,
    dependencies=[Depends(require_sidecar_token)],
)
def supplier_balance(supplier_id: str, session: Session = Depends(get_session)) -> SupplierBalance:
    require_active(session, Supplier, supplier_id, "Firma")
    purchase_total = int(
        session.scalar(
            select(func.coalesce(func.sum(Purchase.received_kurus), 0)).where(
                Purchase.supplier_id == supplier_id, Purchase.status == RecordStatus.ACTIVE
            )
        )
        or 0
    )
    payment_total = int(
        session.scalar(
            select(func.coalesce(func.sum(Payment.amount_kurus), 0)).where(
                Payment.supplier_id == supplier_id, Payment.status == RecordStatus.ACTIVE
            )
        )
        or 0
    )
    return SupplierBalance(
        supplier_id=supplier_id,
        purchase_total_kurus=purchase_total,
        payment_total_kurus=payment_total,
        remaining_kurus=purchase_total - payment_total,
    )


@router.get(
    "/materials/{material_id}/balance",
    response_model=MaterialBalance,
    dependencies=[Depends(require_sidecar_token)],
)
def material_balance(material_id: str, session: Session = Depends(get_session)) -> MaterialBalance:
    material = require_active(session, Material, material_id, "Malzeme")
    if material.tracking_mode == TrackingMode.VALUE_ONLY:
        return MaterialBalance(
            material_id=material.id,
            estimated_quantity=None,
            unit=material.default_unit,
            confidence=material.tracking_mode,
            warning="Bu malzeme yalnızca maliyet üzerinden izleniyor.",
        )
    movements = session.scalars(
        select(MaterialMovement).where(
            MaterialMovement.material_id == material_id,
            MaterialMovement.status == RecordStatus.ACTIVE,
        )
    ).all()
    balance = Decimal(0)
    for item in movements:
        quantity = item.quantity or Decimal(0)
        if item.movement_type in {
            MovementType.PURCHASE,
            MovementType.RETURN,
            MovementType.ADJUSTMENT,
        }:
            balance += quantity
        elif item.movement_type in {MovementType.USE, MovementType.WASTE}:
            balance -= quantity
    warning = (
        "Tahmini miktar sıfırın altında; kullanım veya sayım kaydı eksik olabilir."
        if balance < 0
        else None
    )
    return MaterialBalance(
        material_id=material.id,
        estimated_quantity=balance,
        unit=material.default_unit,
        confidence=material.tracking_mode,
        warning=warning,
    )

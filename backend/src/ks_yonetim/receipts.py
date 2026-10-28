"""Satın alma teslim fişleri.

Borç ve proje maliyeti teslim fişlerinin tarihi ve tutarıyla oluşur. `purchases.received_kurus` aktif
fişlerin toplamıdır ve her fiş eklenip iptal edildiğinde aynı transaction'da senkronlanır; yaşam döngüsü
durumu (`partially_received` / `received`) bu toplamdan türetilir. Fişler silinmez, iptal edilir.
Miktarı olan (veya yalnız-maliyet izlenen) teslimlerde malzeme hareketi teslim anında yazılır.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api import ApiError, add_audit, require_active, require_sidecar_token
from .database import get_session
from .models import (
    Material,
    MaterialMovement,
    MovementType,
    Purchase,
    PurchaseReceipt,
    RecordStatus,
    TrackingMode,
)
from .schemas import OrmModel

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])


def active_receipt_total(session: Session, purchase_id: str) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(PurchaseReceipt.amount_kurus), 0)).where(
                PurchaseReceipt.purchase_id == purchase_id,
                PurchaseReceipt.status == RecordStatus.ACTIVE,
            )
        )
        or 0
    )


def received_quantity(session: Session, purchase_id: str) -> Decimal:
    return Decimal(
        session.scalar(
            select(func.coalesce(func.sum(PurchaseReceipt.quantity), 0)).where(
                PurchaseReceipt.purchase_id == purchase_id,
                PurchaseReceipt.status == RecordStatus.ACTIVE,
            )
        )
        or 0
    )


def quantity_warnings(session: Session, purchase: Purchase) -> list[dict]:
    """Teslim miktarı satın alma miktarını aşarsa engellemez; açıklanabilir uyarı döner."""
    if purchase.quantity is None:
        return []
    received = received_quantity(session, purchase.id)
    if received <= Decimal(purchase.quantity):
        return []
    excess = received - Decimal(purchase.quantity)
    return [
        {
            "code": "quantity_over_received",
            "message": (
                f"Teslim alınan toplam miktar ({received}) satın alma miktarını "
                f"({Decimal(purchase.quantity)}) {excess} aşıyor. Kayıt engellenmedi; "
                "fazla teslim, iade veya hatalı giriş olup olmadığını kontrol edin."
            ),
            "purchase_id": purchase.id,
            "purchase_quantity": str(Decimal(purchase.quantity)),
            "received_quantity": str(received),
            "excess_quantity": str(excess),
        }
    ]


def sync_purchase(session: Session, purchase: Purchase) -> None:
    """received_kurus ve yaşam döngüsü durumunu aktif fişlerden türetir."""
    total = active_receipt_total(session, purchase.id)
    purchase.received_kurus = total
    if purchase.status != RecordStatus.ACTIVE:
        return
    if total <= 0:
        if purchase.lifecycle_state in ("partially_received", "received"):
            purchase.lifecycle_state = "ordered"
    elif total < purchase.total_kurus:
        purchase.lifecycle_state = "partially_received"
    else:
        purchase.lifecycle_state = "received"


def _same_receipt(
    existing: PurchaseReceipt, purchase_id: str, receipt_date: date, amount: int
) -> bool:
    return (
        existing.purchase_id == purchase_id
        and existing.receipt_date == receipt_date
        and existing.amount_kurus == amount
    )


def add_receipt(
    session: Session,
    purchase: Purchase,
    *,
    receipt_date: date,
    amount_kurus: int,
    idempotency_key: str,
    quantity: Decimal | None = None,
    note: str | None = None,
) -> PurchaseReceipt:
    existing = session.scalar(
        select(PurchaseReceipt).where(PurchaseReceipt.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if not _same_receipt(existing, purchase.id, receipt_date, amount_kurus):
            raise ApiError(
                "idempotency_conflict", "Bu anahtar farklı bir teslim için kullanılmış.", 409
            )
        return existing
    if purchase.status != RecordStatus.ACTIVE or purchase.lifecycle_state == "cancelled":
        raise ApiError("not_found", "Satın alma bulunamadı.", 404)
    received = active_receipt_total(session, purchase.id)
    if received + amount_kurus > purchase.total_kurus:
        raise ApiError(
            "receipt_exceeds_total",
            "Teslim toplamı satın alma tutarını aşıyor.",
            409,
            {"remaining_kurus": purchase.total_kurus - received},
        )
    receipt = PurchaseReceipt(
        purchase_id=purchase.id,
        receipt_date=receipt_date,
        quantity=quantity,
        amount_kurus=amount_kurus,
        note=note,
        idempotency_key=idempotency_key,
    )
    session.add(receipt)
    session.flush()
    material = session.get(Material, purchase.material_id)
    if material is not None and (
        quantity is not None or material.tracking_mode == TrackingMode.VALUE_ONLY
    ):
        session.add(
            MaterialMovement(
                material_id=material.id,
                project_id=purchase.project_id,
                purchase_id=purchase.id,
                purchase_receipt_id=receipt.id,
                movement_date=receipt_date,
                movement_type=MovementType.PURCHASE,
                quantity=quantity,
                unit=purchase.unit or material.default_unit,
                amount_kurus=amount_kurus,
                confidence=material.tracking_mode,
            )
        )
    sync_purchase(session, purchase)
    add_audit(
        session,
        "purchase_receipt",
        receipt.id,
        "created",
        {"purchase_id": purchase.id, "amount_kurus": amount_kurus, "receipt_date": receipt_date},
    )
    return receipt


def cancel_receipt(session: Session, receipt: PurchaseReceipt, reason: str | None) -> None:
    receipt.status = RecordStatus.CANCELLED
    receipt.cancelled_at = datetime.now(UTC)
    receipt.cancel_reason = reason
    for movement in session.scalars(
        select(MaterialMovement).where(
            MaterialMovement.purchase_receipt_id == receipt.id,
            MaterialMovement.status == RecordStatus.ACTIVE,
        )
    ):
        movement.status = RecordStatus.CANCELLED
    add_audit(session, "purchase_receipt", receipt.id, "cancelled", {"reason": reason})


def cancel_all_receipts(session: Session, purchase: Purchase, reason: str) -> None:
    for receipt in session.scalars(
        select(PurchaseReceipt).where(
            PurchaseReceipt.purchase_id == purchase.id,
            PurchaseReceipt.status == RecordStatus.ACTIVE,
        )
    ):
        cancel_receipt(session, receipt, reason)
    purchase.received_kurus = 0


class ReceiptCreate(BaseModel):
    receipt_date: date
    amount_kurus: int = Field(gt=0)
    quantity: Decimal | None = Field(default=None, gt=0, decimal_places=3)
    note: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ReceiptCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class ReceiptRead(OrmModel):
    id: str
    purchase_id: str
    receipt_date: date
    quantity: Decimal | None
    amount_kurus: int
    note: str | None
    idempotency_key: str
    status: RecordStatus
    cancelled_at: datetime | None
    cancel_reason: str | None
    warnings: list[dict] = Field(default_factory=list)


@router.post("/purchases/{purchase_id}/receipts", response_model=ReceiptRead, status_code=201)
def create_receipt(
    purchase_id: str, payload: ReceiptCreate, session: Session = Depends(get_session)
):
    purchase = require_active(session, Purchase, purchase_id, "Satın alma")
    try:
        receipt = add_receipt(session, purchase, **payload.model_dump())
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            "idempotency_conflict", "Bu anahtar başka bir kayıtta kullanılmış.", 409
        ) from exc
    session.refresh(receipt)
    read = ReceiptRead.model_validate(receipt)
    read.warnings = quantity_warnings(session, purchase)
    return read


@router.get("/purchases/{purchase_id}/receipts", response_model=list[ReceiptRead])
def list_receipts(
    purchase_id: str, include_cancelled: bool = False, session: Session = Depends(get_session)
):
    purchase = session.get(Purchase, purchase_id)
    if purchase is None:
        raise ApiError("not_found", "Satın alma bulunamadı.", 404)
    query = select(PurchaseReceipt).where(PurchaseReceipt.purchase_id == purchase.id)
    if not include_cancelled:
        query = query.where(PurchaseReceipt.status == RecordStatus.ACTIVE)
    reads = [
        ReceiptRead.model_validate(r)
        for r in session.scalars(query.order_by(PurchaseReceipt.receipt_date, PurchaseReceipt.id))
    ]
    warnings = quantity_warnings(session, purchase)
    for read in reads:
        read.warnings = warnings
    return reads


@router.post("/purchase-receipts/{receipt_id}/cancel", response_model=ReceiptRead)
def cancel_receipt_endpoint(
    receipt_id: str,
    payload: ReceiptCancel | None = None,
    session: Session = Depends(get_session),
):
    receipt = session.get(PurchaseReceipt, receipt_id)
    if receipt is None:
        raise ApiError("not_found", "Teslim kaydı bulunamadı.", 404)
    if receipt.status != RecordStatus.ACTIVE:
        raise ApiError("receipt_cancelled", "Teslim kaydı zaten iptal edilmiş.", 409)
    purchase = session.get(Purchase, receipt.purchase_id)
    cancel_receipt(session, receipt, payload.reason if payload else None)
    session.flush()
    sync_purchase(session, purchase)
    session.commit()
    session.refresh(receipt)
    read = ReceiptRead.model_validate(receipt)
    read.warnings = quantity_warnings(session, purchase)
    return read

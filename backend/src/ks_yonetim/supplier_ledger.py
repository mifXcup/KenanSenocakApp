"""Tedarikçi ekstresi ve tedarikçi bazlı borç yaşlandırması.

Borç, teslim alınan satın alma tutarıyla artar (`received_kurus`); aktif ödemeyle azalır. Terslenen
ödeme ekstrede hem ödeme satırı hem de terslendiği tarihte borcu geri artıran satır olarak görünür.
Kısmi teslimde teslim tarihi ayrı tutulmadığından teslim alınan tutar satın alma tarihinde sayılır.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import ApiError, require_active, require_sidecar_token
from .database import get_session
from .models import Payment, Purchase, RecordStatus, Supplier
from .reports import AGING_LABELS, OVERDUE_KEYS, debt_aging

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_sidecar_token)])
ROW_ORDER = {"purchase": 0, "payment": 1, "payment_reversal": 2}


def _supplier_rows(session: Session, supplier_id: str, date_to: date | None) -> list[dict]:
    rows: list[dict] = []
    purchases = session.scalars(
        select(Purchase).where(
            Purchase.supplier_id == supplier_id, Purchase.status == RecordStatus.ACTIVE
        )
    )
    for purchase in purchases:
        if purchase.received_kurus <= 0:
            continue
        rows.append(
            {
                "row_type": "purchase",
                "source_id": purchase.id,
                "date": purchase.purchase_date,
                "increase_kurus": purchase.received_kurus,
                "decrease_kurus": 0,
                "purchase_id": purchase.id,
                "lifecycle_state": purchase.lifecycle_state,
                "note": purchase.description,
            }
        )
    payments = session.scalars(
        select(Payment).where(
            Payment.supplier_id == supplier_id,
            Payment.status.in_((RecordStatus.ACTIVE, RecordStatus.REVERSED)),
        )
    )
    for payment in payments:
        rows.append(
            {
                "row_type": "payment",
                "source_id": payment.id,
                "date": payment.payment_date,
                "increase_kurus": 0,
                "decrease_kurus": payment.amount_kurus,
                "purchase_id": payment.purchase_id,
                "lifecycle_state": None,
                "note": payment.note,
            }
        )
        if payment.status == RecordStatus.REVERSED and payment.reversed_at is not None:
            rows.append(
                {
                    "row_type": "payment_reversal",
                    "source_id": payment.id,
                    "date": max(payment.reversed_at.date(), payment.payment_date),
                    "increase_kurus": payment.amount_kurus,
                    "decrease_kurus": 0,
                    "purchase_id": payment.purchase_id,
                    "lifecycle_state": None,
                    "note": "Ödeme ters kaydı",
                }
            )
    rows = [r for r in rows if date_to is None or r["date"] <= date_to]
    rows.sort(key=lambda r: (r["date"], ROW_ORDER[r["row_type"]], r["source_id"]))
    return rows


@router.get("/suppliers/{supplier_id}/statement")
def supplier_statement(
    supplier_id: str,
    session: Session = Depends(get_session),
    date_from: date | None = None,
    date_to: date | None = None,
):
    supplier = require_active(session, Supplier, supplier_id, "Firma")
    if date_from and date_to and date_from > date_to:
        raise ApiError("invalid_range", "Başlangıç tarihi bitiş tarihinden sonra olamaz.", 422)
    rows = _supplier_rows(session, supplier.id, date_to)
    opening = sum(
        r["increase_kurus"] - r["decrease_kurus"] for r in rows if date_from and r["date"] < date_from
    )
    running = opening
    lines = []
    for row in rows:
        if date_from and row["date"] < date_from:
            continue
        running += row["increase_kurus"] - row["decrease_kurus"]
        lines.append({**row, "balance_kurus": running})
    return {
        "supplier_id": supplier.id,
        "supplier_name": supplier.name,
        "date_from": date_from,
        "date_to": date_to,
        "opening_balance_kurus": opening,
        "total_increase_kurus": sum(r["increase_kurus"] for r in lines),
        "total_decrease_kurus": sum(r["decrease_kurus"] for r in lines),
        "closing_balance_kurus": running,
        "rows": lines,
    }


@router.get("/suppliers/{supplier_id}/aging")
def supplier_aging(
    supplier_id: str, session: Session = Depends(get_session), as_of: date | None = None
):
    supplier = require_active(session, Supplier, supplier_id, "Firma")
    day = as_of or date.today()
    report = debt_aging(session, day)
    items = [item for item in report.items if item.supplier_id == supplier.id]
    totals = {key: [0, 0] for key in AGING_LABELS}
    for item in items:
        totals[item.bucket][0] += item.remaining_kurus
        totals[item.bucket][1] += 1
    row = next((s for s in report.suppliers if s.supplier_id == supplier.id), None)
    return {
        "supplier_id": supplier.id,
        "as_of": day,
        "total_open_kurus": sum(v[0] for v in totals.values()),
        "overdue_kurus": sum(totals[key][0] for key in OVERDUE_KEYS),
        "credit_kurus": row.credit_kurus if row else 0,
        "buckets": [
            {"key": key, "label": AGING_LABELS[key], "amount_kurus": v[0], "count": v[1]}
            for key, v in totals.items()
        ],
        "items": [item.model_dump() for item in items],
    }

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Material, Payment, Purchase, PurchaseReceipt, RecordStatus, Supplier
from .schemas import (
    AgingBucket,
    AgingItem,
    AgingSupplier,
    DebtAgingReport,
    MaterialReportRow,
    MonthReportRow,
    PurchaseReport,
    SupplierReportRow,
)

AGING_LABELS = {
    "not_due": "Vadesi gelmemiş",
    "d1_30": "1–30 gün gecikmiş",
    "d31_60": "31–60 gün gecikmiş",
    "d61_90": "61–90 gün gecikmiş",
    "d90_plus": "90 günden fazla gecikmiş",
    "no_due_date": "Vade girilmemiş",
}
OVERDUE_KEYS = ("d1_30", "d31_60", "d61_90", "d90_plus")


def aging_bucket(due_date: date | None, as_of: date) -> tuple[str, int | None]:
    if due_date is None:
        return "no_due_date", None
    overdue_days = (as_of - due_date).days
    if overdue_days <= 0:
        return "not_due", 0
    if overdue_days <= 30:
        return "d1_30", overdue_days
    if overdue_days <= 60:
        return "d31_60", overdue_days
    if overdue_days <= 90:
        return "d61_90", overdue_days
    return "d90_plus", overdue_days


def debt_aging(session: Session, as_of: date) -> DebtAgingReport:
    purchases = session.execute(
        select(Purchase, Supplier.name, Material.name)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .join(Material, Material.id == Purchase.material_id)
        .where(Purchase.status == RecordStatus.ACTIVE)
    ).all()
    received_as_of: dict[str, int] = {
        purchase_id: int(amount)
        for purchase_id, amount in session.execute(
            select(PurchaseReceipt.purchase_id, func.sum(PurchaseReceipt.amount_kurus))
            .where(PurchaseReceipt.status == RecordStatus.ACTIVE, PurchaseReceipt.receipt_date <= as_of)
            .group_by(PurchaseReceipt.purchase_id)
        )
    }

    linked_paid: dict[str, int] = defaultdict(int)
    unlinked_by_supplier: dict[str, int] = defaultdict(int)
    for purchase_id, supplier_id, amount in session.execute(
        select(Payment.purchase_id, Payment.supplier_id, func.sum(Payment.amount_kurus))
        .where(Payment.status == RecordStatus.ACTIVE, Payment.payment_date <= as_of)
        .group_by(Payment.purchase_id, Payment.supplier_id)
    ):
        if purchase_id:
            linked_paid[purchase_id] += int(amount)
        else:
            unlinked_by_supplier[supplier_id] += int(amount)

    by_supplier: dict[str, list[tuple[Purchase, str, int]]] = defaultdict(list)
    supplier_names: dict[str, str] = {}
    material_names: dict[str, str] = {}
    # Planlı/siparişli veya kısmi teslimli satın almaya teslimden fazla yapılan bağlı ödeme avanstır.
    for purchase, supplier_name, material_name in purchases:
        paid_here = linked_paid.get(purchase.id, 0)
        received_here = received_as_of.get(purchase.id, 0)
        remaining = max(0, received_here - paid_here)
        unlinked_by_supplier[purchase.supplier_id] += max(0, paid_here - received_here)
        by_supplier[purchase.supplier_id].append((purchase, material_name, remaining))
        supplier_names[purchase.supplier_id] = supplier_name
        material_names[purchase.id] = material_name

    # Firmaya doğrudan yapılan (alışa bağlanmamış) ödemeler en eski borçtan düşülür.
    credit_by_supplier: dict[str, int] = {}
    items: list[AgingItem] = []
    for supplier_id, entries in by_supplier.items():
        entries.sort(key=lambda e: (e[0].due_date or e[0].purchase_date, e[0].purchase_date))
        pool = unlinked_by_supplier.get(supplier_id, 0)
        for purchase, material_name, remaining in entries:
            applied = min(pool, remaining)
            pool -= applied
            remaining -= applied
            if remaining <= 0:
                continue
            bucket, overdue_days = aging_bucket(purchase.due_date, as_of)
            items.append(
                AgingItem(
                    purchase_id=purchase.id,
                    supplier_id=supplier_id,
                    supplier_name=supplier_names[supplier_id],
                    material_name=material_name,
                    purchase_date=purchase.purchase_date,
                    due_date=purchase.due_date,
                    total_kurus=purchase.total_kurus,
                    remaining_kurus=remaining,
                    days_overdue=overdue_days,
                    bucket=bucket,
                )
            )
        if pool > 0:
            credit_by_supplier[supplier_id] = pool
    for supplier_id, amount in unlinked_by_supplier.items():
        if supplier_id not in by_supplier and amount > 0:
            credit_by_supplier[supplier_id] = amount
    missing = [s for s in credit_by_supplier if s not in supplier_names]
    if missing:
        for supplier_id, name in session.execute(
            select(Supplier.id, Supplier.name).where(Supplier.id.in_(missing))
        ):
            supplier_names[supplier_id] = name

    items.sort(key=lambda i: (i.due_date or date.max, i.purchase_date))

    bucket_totals = {key: [0, 0] for key in AGING_LABELS}
    suppliers: dict[str, AgingSupplier] = {}
    for item in items:
        bucket_totals[item.bucket][0] += item.remaining_kurus
        bucket_totals[item.bucket][1] += 1
        row = suppliers.setdefault(
            item.supplier_id,
            AgingSupplier(
                supplier_id=item.supplier_id,
                supplier_name=item.supplier_name,
                total_open_kurus=0,
                overdue_kurus=0,
                credit_kurus=0,
                buckets={key: 0 for key in AGING_LABELS},
            ),
        )
        row.total_open_kurus += item.remaining_kurus
        row.buckets[item.bucket] += item.remaining_kurus
        if item.bucket in OVERDUE_KEYS:
            row.overdue_kurus += item.remaining_kurus
    for supplier_id, credit in credit_by_supplier.items():
        row = suppliers.setdefault(
            supplier_id,
            AgingSupplier(
                supplier_id=supplier_id,
                supplier_name=supplier_names.get(supplier_id, "Bilinmiyor"),
                total_open_kurus=0,
                overdue_kurus=0,
                credit_kurus=0,
                buckets={key: 0 for key in AGING_LABELS},
            ),
        )
        row.credit_kurus = credit

    return DebtAgingReport(
        as_of=as_of,
        total_open_kurus=sum(v[0] for v in bucket_totals.values()),
        overdue_kurus=sum(bucket_totals[k][0] for k in OVERDUE_KEYS),
        credit_kurus=sum(credit_by_supplier.values()),
        buckets=[
            AgingBucket(key=key, label=AGING_LABELS[key], amount_kurus=v[0], count=v[1])
            for key, v in bucket_totals.items()
        ],
        suppliers=sorted(suppliers.values(), key=lambda s: -s.total_open_kurus),
        items=items,
    )


def purchase_report(
    session: Session,
    date_from: date | None,
    date_to: date | None,
    supplier_id: str | None,
    project_id: str | None,
) -> PurchaseReport:
    query = (
        select(PurchaseReceipt, Purchase, Supplier.name, Material.name)
        .join(Purchase, Purchase.id == PurchaseReceipt.purchase_id)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .join(Material, Material.id == Purchase.material_id)
        .where(
            Purchase.status == RecordStatus.ACTIVE,
            PurchaseReceipt.status == RecordStatus.ACTIVE,
        )
    )
    if date_from:
        query = query.where(PurchaseReceipt.receipt_date >= date_from)
    if date_to:
        query = query.where(PurchaseReceipt.receipt_date <= date_to)
    if supplier_id:
        query = query.where(Purchase.supplier_id == supplier_id)
    if project_id:
        query = query.where(Purchase.project_id == project_id)
    rows = session.execute(query.order_by(PurchaseReceipt.receipt_date, PurchaseReceipt.id)).all()

    suppliers: dict[str, SupplierReportRow] = {}
    materials: dict[tuple[str, str | None], MaterialReportRow] = {}
    months: dict[str, MonthReportRow] = {}
    seen: set[tuple[str, str, object]] = set()
    purchase_total = 0

    def first_time(kind: str, key: object, purchase_id: str) -> bool:
        marker = (kind, purchase_id, key)
        if marker in seen:
            return False
        seen.add(marker)
        return True

    for receipt, purchase, supplier_name, material_name in rows:
        amount = receipt.amount_kurus
        purchase_total += amount
        srow = suppliers.setdefault(
            purchase.supplier_id,
            SupplierReportRow(
                supplier_id=purchase.supplier_id,
                supplier_name=supplier_name,
                purchase_count=0,
                purchase_total_kurus=0,
                payment_total_kurus=0,
                current_debt_kurus=0,
            ),
        )
        if first_time("supplier", purchase.supplier_id, purchase.id):
            srow.purchase_count += 1
        srow.purchase_total_kurus += amount

        mkey = (purchase.material_id, purchase.unit)
        mrow = materials.setdefault(
            mkey,
            MaterialReportRow(
                material_id=purchase.material_id,
                material_name=material_name,
                unit=purchase.unit,
                purchase_count=0,
                quantity=None,
                total_kurus=0,
            ),
        )
        if first_time("material", mkey, purchase.id):
            mrow.purchase_count += 1
        mrow.total_kurus += amount
        if receipt.quantity is not None:
            mrow.quantity = (mrow.quantity or Decimal(0)) + receipt.quantity

        key = receipt.receipt_date.strftime("%Y-%m")
        month = months.setdefault(key, MonthReportRow(month=key, purchase_count=0, total_kurus=0))
        if first_time("month", key, purchase.id):
            month.purchase_count += 1
        month.total_kurus += amount

    payment_query = select(Payment.supplier_id, func.sum(Payment.amount_kurus)).where(
        Payment.status == RecordStatus.ACTIVE
    )
    if date_from:
        payment_query = payment_query.where(Payment.payment_date >= date_from)
    if date_to:
        payment_query = payment_query.where(Payment.payment_date <= date_to)
    if supplier_id:
        payment_query = payment_query.where(Payment.supplier_id == supplier_id)
    if project_id:
        payment_query = payment_query.join(Purchase, Purchase.id == Payment.purchase_id).where(
            Purchase.project_id == project_id
        )
    payment_total = 0
    paid_by_supplier = dict(session.execute(payment_query.group_by(Payment.supplier_id)).all())
    for sid, amount in paid_by_supplier.items():
        payment_total += int(amount)

    missing = [sid for sid in paid_by_supplier if sid not in suppliers]
    for sid, name in (
        session.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(missing))).all()
        if missing
        else []
    ):
        suppliers[sid] = SupplierReportRow(
            supplier_id=sid,
            supplier_name=name,
            purchase_count=0,
            purchase_total_kurus=0,
            payment_total_kurus=0,
            current_debt_kurus=0,
        )

    if suppliers:
        ids = list(suppliers)
        bought = dict(
            session.execute(
                select(Purchase.supplier_id, func.sum(Purchase.received_kurus))
                .where(Purchase.status == RecordStatus.ACTIVE, Purchase.supplier_id.in_(ids))
                .group_by(Purchase.supplier_id)
            ).all()
        )
        paid = dict(
            session.execute(
                select(Payment.supplier_id, func.sum(Payment.amount_kurus))
                .where(Payment.status == RecordStatus.ACTIVE, Payment.supplier_id.in_(ids))
                .group_by(Payment.supplier_id)
            ).all()
        )
        for sid, row in suppliers.items():
            row.payment_total_kurus = int(paid_by_supplier.get(sid, 0))
            row.current_debt_kurus = int(bought.get(sid, 0)) - int(paid.get(sid, 0))

    return PurchaseReport(
        date_from=date_from,
        date_to=date_to,
        purchase_count=len(rows),
        purchase_total_kurus=purchase_total,
        payment_total_kurus=payment_total,
        by_supplier=sorted(suppliers.values(), key=lambda s: -s.purchase_total_kurus),
        by_material=sorted(materials.values(), key=lambda m: -m.total_kurus),
        by_month=sorted(months.values(), key=lambda m: m.month),
    )

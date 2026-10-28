"""customer payment allocations, purchase receipts, manual cost forecasts

Revision ID: d2b8f6a1c4e7
Revises: c1a7e9d2b3f4
Create Date: 2026-10-28 14:00:00
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "d2b8f6a1c4e7"
down_revision: str | None = "c1a7e9d2b3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "purchase_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "purchase_id",
            sa.String(36),
            sa.ForeignKey("purchases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3)),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("status", record_status, nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(255)),
        *_timestamps(),
    )
    op.create_index("ix_purchase_receipts_purchase_id", "purchase_receipts", ["purchase_id"])
    op.create_index("ix_purchase_receipts_receipt_date", "purchase_receipts", ["receipt_date"])
    op.create_index("ix_purchase_receipts_status", "purchase_receipts", ["status"])

    op.execute(
        "ALTER TABLE material_movements ADD COLUMN purchase_receipt_id VARCHAR(36) "
        "REFERENCES purchase_receipts (id)"
    )
    op.create_index(
        "ix_material_movements_purchase_receipt_id", "material_movements", ["purchase_receipt_id"]
    )

    op.create_table(
        "customer_payment_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "customer_id",
            sa.String(36),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "collection_id",
            sa.String(36),
            sa.ForeignKey("customer_financial_movements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "receivable_schedule_id",
            sa.String(36),
            sa.ForeignKey("receivable_schedules.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("allocation_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("status", record_status, nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(255)),
        *_timestamps(),
    )
    for column in ("customer_id", "collection_id", "receivable_schedule_id", "status"):
        op.create_index(
            f"ix_customer_payment_allocations_{column}", "customer_payment_allocations", [column]
        )

    op.create_table(
        "project_cost_forecasts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("remaining_estimate_kurus", sa.Integer()),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "category", "revision_no", name="uq_cost_forecast_revision"),
    )
    op.create_index(
        "ix_cost_forecast_project_category", "project_cost_forecasts", ["project_id", "category"]
    )
    op.create_index("ix_project_cost_forecasts_status", "project_cost_forecasts", ["status"])

    _backfill_receipts()
    _backfill_allocations()


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _backfill_receipts() -> None:
    """Teslim alınmış her mevcut satın alma, satın alma tarihinde tek başlangıç fişine dönüşür."""
    bind = op.get_bind()
    stamp = _stamp()
    rows = bind.execute(
        sa.text(
            "SELECT id, purchase_date, quantity, received_kurus FROM purchases "
            "WHERE status = 'ACTIVE' AND received_kurus > 0 ORDER BY id"
        )
    ).all()
    if not rows:
        return
    columns = (
        "id", "purchase_id", "receipt_date", "quantity", "amount_kurus", "note",
        "idempotency_key", "status", "created_at", "updated_at",
    )
    table = sa.table("purchase_receipts", *[sa.column(name) for name in columns])
    op.bulk_insert(
        table,
        [
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ks-legacy-receipt:{pid}")),
                "purchase_id": pid,
                "receipt_date": str(pdate)[:10],
                "quantity": qty,
                "amount_kurus": received,
                "note": "Başlangıç teslim kaydı (migration)",
                "idempotency_key": f"legacy-receipt:{pid}",
                "status": "ACTIVE",
                "created_at": stamp,
                "updated_at": stamp,
            }
            for pid, pdate, qty, received in rows
        ],
    )
    bind.execute(
        sa.text(
            "UPDATE material_movements SET purchase_receipt_id = ("
            "SELECT r.id FROM purchase_receipts r WHERE r.purchase_id = material_movements.purchase_id"
            ") WHERE movement_type = 'PURCHASE' AND purchase_id IS NOT NULL"
        )
    )


def _backfill_allocations() -> None:
    """Plana bağlı mevcut tahsilatlar dağıtım kaydına dönüşür (terslenmişler iptal durumunda)."""
    bind = op.get_bind()
    stamp = _stamp()
    rows = bind.execute(
        sa.text(
            "SELECT m.id, m.customer_id, m.receivable_schedule_id, m.amount_kurus, m.movement_date, "
            "EXISTS (SELECT 1 FROM customer_financial_movements r "
            "WHERE r.reversed_movement_id = m.id AND r.status = 'ACTIVE') "
            "FROM customer_financial_movements m "
            "WHERE m.movement_type = 'collection' AND m.status = 'ACTIVE' "
            "AND m.receivable_schedule_id IS NOT NULL ORDER BY m.id"
        )
    ).all()
    if not rows:
        return
    columns = (
        "id", "customer_id", "collection_id", "receivable_schedule_id", "amount_kurus",
        "allocation_date", "idempotency_key", "status", "cancelled_at", "cancel_reason",
        "created_at", "updated_at",
    )
    table = sa.table("customer_payment_allocations", *[sa.column(name) for name in columns])
    op.bulk_insert(
        table,
        [
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ks-legacy-allocation:{mid}")),
                "customer_id": customer_id,
                "collection_id": mid,
                "receivable_schedule_id": schedule_id,
                "amount_kurus": amount,
                "allocation_date": str(day)[:10],
                "idempotency_key": f"legacy-allocation:{mid}",
                "status": "CANCELLED" if voided else "ACTIVE",
                "cancelled_at": stamp if voided else None,
                "cancel_reason": "Migration: terslenmiş tahsilat" if voided else None,
                "created_at": stamp,
                "updated_at": stamp,
            }
            for mid, customer_id, schedule_id, amount, day, voided in rows
        ],
    )


def downgrade() -> None:
    op.drop_table("project_cost_forecasts")
    op.drop_table("customer_payment_allocations")
    op.drop_index("ix_material_movements_purchase_receipt_id", table_name="material_movements")
    with op.batch_alter_table("material_movements") as batch:
        batch.drop_column("purchase_receipt_id")
    op.drop_table("purchase_receipts")

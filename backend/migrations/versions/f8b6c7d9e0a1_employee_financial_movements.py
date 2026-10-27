"""employee financial movement ledger (migrates v0.2.0 employee payments)

Revision ID: f8b6c7d9e0a1
Revises: e7a5b6c8d9f0
Create Date: 2026-10-27 12:00:00
"""
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "f8b6c7d9e0a1"
down_revision: str | None = "e7a5b6c8d9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")
COLUMNS = (
    "id",
    "employee_id",
    "movement_date",
    "movement_type",
    "direction",
    "amount_kurus",
    "note",
    "idempotency_key",
    "reversed_movement_id",
    "source",
    "status",
    "created_at",
    "updated_at",
)


def upgrade() -> None:
    op.create_table(
        "employee_financial_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "employee_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payroll_period_id",
            sa.String(36),
            sa.ForeignKey("payroll_periods.id", ondelete="RESTRICT"),
        ),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT")),
        sa.Column("site_id", sa.String(36), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("movement_date", sa.Date(), nullable=False),
        sa.Column("movement_type", sa.String(24), nullable=False),
        sa.Column("direction", sa.String(24), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("note", sa.Text()),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "reversed_movement_id",
            sa.String(36),
            sa.ForeignKey("employee_financial_movements.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_emp_movement_employee_date",
        "employee_financial_movements",
        ["employee_id", "movement_date"],
    )
    op.create_index(
        "ix_emp_movement_period",
        "employee_financial_movements",
        ["payroll_period_id", "movement_type"],
    )
    op.create_index(
        "ix_employee_financial_movements_movement_date",
        "employee_financial_movements",
        ["movement_date"],
    )
    op.create_index(
        "ix_employee_financial_movements_movement_type",
        "employee_financial_movements",
        ["movement_type"],
    )
    op.create_index(
        "ix_employee_financial_movements_status", "employee_financial_movements", ["status"]
    )

    # v0.2.0 personel ödemeleri deftere aynı kimlikle taşınır; eski tablo olduğu gibi kalır.
    bind = op.get_bind()
    table = sa.table("employee_financial_movements", *[sa.column(name) for name in COLUMNS])
    now = datetime.now(UTC)
    originals, reversals = [], []
    for pid, employee_id, pay_date, amount, ptype, note, status in bind.execute(
        sa.text(
            "SELECT id, employee_id, payment_date, amount_kurus, payment_type, note, status "
            "FROM employee_payments ORDER BY id"
        )
    ):
        day = date.fromisoformat(str(pay_date)[:10])
        advance = str(ptype).upper() == "ADVANCE"
        originals.append(
            {
                "id": pid,
                "employee_id": employee_id,
                "movement_date": day,
                "movement_type": "advance" if advance else "payroll_payment",
                "direction": "employee_owes_company" if advance else "company_owes_employee",
                "amount_kurus": amount,
                "note": note,
                "idempotency_key": f"legacy-payment:{pid}",
                "reversed_movement_id": None,
                "source": "legacy",
                "status": "ACTIVE",
                "created_at": now,
                "updated_at": now,
            }
        )
        if str(status).upper() == "REVERSED":
            reversals.append(
                {
                    "id": f"legacy-reversal-{pid}"[:36],
                    "employee_id": employee_id,
                    "movement_date": day,
                    "movement_type": "reversal",
                    "direction": "company_owes_employee" if advance else "employee_owes_company",
                    "amount_kurus": amount,
                    "note": "v0.2.0 ters kaydı",
                    "idempotency_key": f"legacy-reversal:{pid}",
                    "reversed_movement_id": pid,
                    "source": "legacy",
                    "status": "ACTIVE",
                    "created_at": now,
                    "updated_at": now,
                }
            )
    if originals:
        op.bulk_insert(table, originals)
    if reversals:
        op.bulk_insert(table, reversals)


def downgrade() -> None:
    op.drop_table("employee_financial_movements")

"""expand employees and add wage rate history

Revision ID: c5e3f4a6b7d8
Revises: b4d2e3f5a6c7
Create Date: 2026-10-27 09:00:00
"""
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "c5e3f4a6b7d8"
down_revision: str | None = "b4d2e3f5a6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")


def _to_date(raw: object) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(str(raw)[:10])


def upgrade() -> None:
    op.add_column("employees", sa.Column("employment_start_date", sa.Date()))
    op.add_column("employees", sa.Column("employment_end_date", sa.Date()))
    op.add_column(
        "employees",
        sa.Column("employment_state", sa.String(16), nullable=False, server_default="active"),
    )
    op.add_column(
        "employees",
        sa.Column("wage_type", sa.String(16), nullable=False, server_default="daily"),
    )
    op.add_column("employees", sa.Column("current_rate_kurus", sa.Integer()))
    op.add_column("employees", sa.Column("iban", sa.String(34)))
    op.add_column("employees", sa.Column("payment_note", sa.Text()))
    op.create_index("ix_employees_employment_state", "employees", ["employment_state"])

    op.create_table(
        "employee_wage_rates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "employee_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("wage_type", sa.String(16), nullable=False),
        sa.Column("rate_kurus", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255)),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_wage_rate_employee_from", "employee_wage_rates", ["employee_id", "effective_from"]
    )
    op.create_index("ix_employee_wage_rates_status", "employee_wage_rates", ["status"])

    # Veri kaybı olmadan: eski günlük ücret yeni ücret modeline taşınır; daily_rate_kurus korunur.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE employees SET wage_type = 'daily', current_rate_kurus = daily_rate_kurus "
            "WHERE daily_rate_kurus IS NOT NULL"
        )
    )
    first_work = {
        employee_id: _to_date(first_day)
        for employee_id, first_day in bind.execute(
            sa.text("SELECT employee_id, MIN(work_date) FROM work_logs GROUP BY employee_id")
        )
    }
    now = datetime.now(UTC)
    rate_table = sa.table(
        "employee_wage_rates",
        sa.column("id", sa.String),
        sa.column("employee_id", sa.String),
        sa.column("effective_from", sa.Date),
        sa.column("effective_to", sa.Date),
        sa.column("wage_type", sa.String),
        sa.column("rate_kurus", sa.Integer),
        sa.column("reason", sa.String),
        sa.column("status", record_status),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    rows = []
    for employee_id, created_at, rate in bind.execute(
        sa.text(
            "SELECT id, created_at, daily_rate_kurus FROM employees "
            "WHERE daily_rate_kurus IS NOT NULL ORDER BY id"
        )
    ):
        start = min(
            day for day in (first_work.get(employee_id), _to_date(created_at)) if day is not None
        )
        rows.append(
            {
                "id": f"legacy-rate-{employee_id}",
                "employee_id": employee_id,
                "effective_from": start,
                "effective_to": None,
                "wage_type": "daily",
                "rate_kurus": rate,
                "reason": "v0.2.0 günlük ücretinden taşındı",
                "status": "ACTIVE",
                "created_at": now,
                "updated_at": now,
            }
        )
    if rows:
        op.bulk_insert(rate_table, rows)


def downgrade() -> None:
    op.drop_table("employee_wage_rates")
    op.drop_index("ix_employees_employment_state", table_name="employees")
    with op.batch_alter_table("employees") as batch:
        for column in (
            "payment_note",
            "iban",
            "current_rate_kurus",
            "wage_type",
            "employment_state",
            "employment_end_date",
            "employment_start_date",
        ):
            batch.drop_column(column)

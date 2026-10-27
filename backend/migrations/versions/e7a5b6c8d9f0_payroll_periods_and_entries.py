"""payroll periods and entries

Revision ID: e7a5b6c8d9f0
Revises: d6f4a5b7c8e9
Create Date: 2026-10-27 11:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a5b6c8d9f0"
down_revision: str | None = "d6f4a5b7c8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")


def upgrade() -> None:
    op.create_table(
        "payroll_periods",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("overtime_multiplier_percent", sa.Integer()),
        sa.Column("calculated_at", sa.DateTime(timezone=True)),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payroll_periods_period_start", "payroll_periods", ["period_start"])
    op.create_index("ix_payroll_periods_state", "payroll_periods", ["state"])
    op.create_index("ix_payroll_periods_status", "payroll_periods", ["status"])
    op.create_table(
        "payroll_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "payroll_period_id",
            sa.String(36),
            sa.ForeignKey("payroll_periods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("wage_type", sa.String(16), nullable=False),
        sa.Column("base_rate_kurus", sa.Integer(), nullable=False),
        sa.Column("normal_hours", sa.Numeric(8, 2), nullable=False),
        sa.Column("overtime_hours", sa.Numeric(8, 2), nullable=False),
        sa.Column("worked_days", sa.Numeric(6, 2), nullable=False),
        sa.Column("base_earning_kurus", sa.Integer(), nullable=False),
        sa.Column("overtime_earning_kurus", sa.Integer(), nullable=False),
        sa.Column("bonus_kurus", sa.Integer(), nullable=False),
        sa.Column("additional_earning_kurus", sa.Integer(), nullable=False),
        sa.Column("deduction_kurus", sa.Integer(), nullable=False),
        sa.Column("advance_deduction_kurus", sa.Integer(), nullable=False),
        sa.Column("gross_earning_kurus", sa.Integer(), nullable=False),
        sa.Column("net_due_kurus", sa.Integer(), nullable=False),
        sa.Column("paid_kurus", sa.Integer(), nullable=False),
        sa.Column("remaining_kurus", sa.Integer(), nullable=False),
        sa.Column("calculation_detail", sa.JSON()),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("payroll_period_id", "employee_id", name="uq_payroll_entry_employee"),
    )
    op.create_index("ix_payroll_entries_payroll_period_id", "payroll_entries", ["payroll_period_id"])
    op.create_index("ix_payroll_entries_employee_id", "payroll_entries", ["employee_id"])
    op.create_index("ix_payroll_entries_status", "payroll_entries", ["status"])


def downgrade() -> None:
    op.drop_table("payroll_entries")
    op.drop_table("payroll_periods")

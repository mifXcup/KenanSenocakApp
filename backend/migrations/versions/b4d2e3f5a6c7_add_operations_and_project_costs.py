"""add operations and project costs

Revision ID: b4d2e3f5a6c7
Revises: a3c1d2e4f5b6
Create Date: 2026-10-26 02:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d2e3f5a6c7"
down_revision: str | None = "a3c1d2e4f5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("phone", sa.String(40)),
        sa.Column("role", sa.String(120)),
        sa.Column("daily_rate_kurus", sa.Integer()),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_employees_name", "employees", ["name"])
    op.create_index("ix_employees_status", "employees", ["status"])
    op.create_table(
        "sites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT")),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sites_name", "sites", ["name"])
    op.create_index("ix_sites_status", "sites", ["status"])
    op.create_table(
        "work_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT")),
        sa.Column("site_id", sa.String(36), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("hours", sa.Numeric(5, 2), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_work_logs_work_date", "work_logs", ["work_date"])
    op.create_index("ix_work_logs_status", "work_logs", ["status"])
    op.create_index("ix_work_log_employee_date", "work_logs", ["employee_id", "work_date"])
    op.create_index("ix_work_log_project_date", "work_logs", ["project_id", "work_date"])
    op.create_table(
        "employee_payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("payment_type", sa.Enum("ADVANCE", "WAGE", name="employeepaymenttype"), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_employee_payments_payment_date", "employee_payments", ["payment_date"])
    op.create_index("ix_employee_payments_payment_type", "employee_payments", ["payment_type"])
    op.create_index("ix_employee_payments_status", "employee_payments", ["status"])
    op.create_index("ix_employee_payment_date", "employee_payments", ["employee_id", "payment_date"])
    op.create_table(
        "project_expenses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", sa.String(36), sa.ForeignKey("sites.id", ondelete="RESTRICT")),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("category", sa.Enum("SHIPPING", "INSTALLATION", "SITE", "OTHER", name="expensecategory"), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_project_expenses_expense_date", "project_expenses", ["expense_date"])
    op.create_index("ix_project_expenses_status", "project_expenses", ["status"])
    op.create_index("ix_project_expense_date", "project_expenses", ["project_id", "expense_date"])


def downgrade() -> None:
    op.drop_table("project_expenses")
    op.drop_table("employee_payments")
    op.drop_table("work_logs")
    op.drop_table("sites")
    op.drop_table("employees")

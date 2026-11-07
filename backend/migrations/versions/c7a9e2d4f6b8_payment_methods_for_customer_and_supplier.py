"""store payment method for customer collections and supplier payments

Revision ID: c7a9e2d4f6b8
Revises: f9b8c7d6e5a4
Create Date: 2026-11-07 12:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a9e2d4f6b8"
down_revision: str | None = "f9b8c7d6e5a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "payment_method" not in {column["name"] for column in inspector.get_columns("payments")}:
        op.add_column("payments", sa.Column("payment_method", sa.String(24), nullable=True))
    if "payment_method" not in {
        column["name"] for column in inspector.get_columns("customer_financial_movements")
    }:
        op.add_column(
            "customer_financial_movements", sa.Column("payment_method", sa.String(24), nullable=True)
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "payment_method" in {
        column["name"] for column in inspector.get_columns("customer_financial_movements")
    }:
        op.drop_column("customer_financial_movements", "payment_method")
    if "payment_method" in {column["name"] for column in inspector.get_columns("payments")}:
        op.drop_column("payments", "payment_method")

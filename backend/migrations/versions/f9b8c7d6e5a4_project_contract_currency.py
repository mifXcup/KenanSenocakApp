"""Keep the agreed foreign currency amount and its TL conversion rate.

Revision ID: f9b8c7d6e5a4
Revises: e8a7c6d5b4f3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9b8c7d6e5a4"
down_revision: str | None = "e8a7c6d5b4f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("contract_currency", sa.String(3), nullable=False, server_default="TRY"))
    op.add_column("projects", sa.Column("contract_foreign_amount_minor", sa.Integer()))
    op.add_column("projects", sa.Column("contract_fx_rate", sa.Numeric(18, 6)))


def downgrade() -> None:
    op.drop_column("projects", "contract_fx_rate")
    op.drop_column("projects", "contract_foreign_amount_minor")
    op.drop_column("projects", "contract_currency")

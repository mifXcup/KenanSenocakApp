"""add purchase due date

Revision ID: a3c1d2e4f5b6
Revises: 1597ff061a94
Create Date: 2026-10-25 21:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a3c1d2e4f5b6'
down_revision: str | None = '1597ff061a94'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('purchases') as batch:
        batch.add_column(sa.Column('due_date', sa.Date(), nullable=True))
        batch.create_index('ix_purchases_due_date', ['due_date'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('purchases') as batch:
        batch.drop_index('ix_purchases_due_date')
        batch.drop_column('due_date')

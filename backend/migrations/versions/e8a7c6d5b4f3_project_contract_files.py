"""Store project contract documents in the backed-up database.

Revision ID: e8a7c6d5b4f3
Revises: b7d3f1a9c5e2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8a7c6d5b4f3"
down_revision: str | None = "b7d3f1a9c5e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_contracts",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("file_name", sa.String(180), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("project_contracts")

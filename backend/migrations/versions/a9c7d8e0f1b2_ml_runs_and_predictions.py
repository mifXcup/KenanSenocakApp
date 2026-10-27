"""local machine learning run and prediction history

Revision ID: a9c7d8e0f1b2
Revises: f8b6c7d9e0a1
Create Date: 2026-10-27 13:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c7d8e0f1b2"
down_revision: str | None = "f8b6c7d9e0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ml_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_name", sa.String(40), nullable=False),
        sa.Column("model_version", sa.String(24), nullable=False),
        sa.Column("trained_from", sa.Date()),
        sa.Column("trained_to", sa.Date()),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.JSON()),
        sa.Column("metrics", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ml_runs_model_name", "ml_runs", ["model_name"])
    op.create_index("ix_ml_runs_created_at", "ml_runs", ["created_at"])
    op.create_table(
        "ml_predictions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "ml_run_id",
            sa.String(36),
            sa.ForeignKey("ml_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("prediction_type", sa.String(40), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(80), nullable=False),
        sa.Column("prediction_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date()),
        sa.Column("predicted_value", sa.Float()),
        sa.Column("confidence", sa.Float()),
        sa.Column("explanation", sa.JSON()),
        sa.Column("actual_value", sa.Float()),
        sa.Column("evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("user_feedback", sa.String(24)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ml_predictions_ml_run_id", "ml_predictions", ["ml_run_id"])
    op.create_index("ix_ml_predictions_prediction_date", "ml_predictions", ["prediction_date"])
    op.create_index("ix_ml_predictions_target_date", "ml_predictions", ["target_date"])
    op.create_index(
        "ix_ml_prediction_entity", "ml_predictions", ["prediction_type", "entity_id"]
    )


def downgrade() -> None:
    op.drop_table("ml_predictions")
    op.drop_table("ml_runs")

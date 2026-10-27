"""add single-user project command center

Revision ID: d6f4a7b8c9d0
Revises: c5e3f4a6b7d8
Create Date: 2026-10-27 19:30:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6f4a7b8c9d0"
down_revision: str | None = "c5e3f4a6b7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.add_column("projects", sa.Column("stage", sa.String(32), nullable=False, server_default="planning"))
    op.add_column("projects", sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("projects", sa.Column("accent_color", sa.String(16), nullable=False, server_default="#9A5A3A"))
    op.add_column("projects", sa.Column("address", sa.Text()))
    op.add_column("projects", sa.Column("next_step", sa.String(280)))
    op.create_index("ix_projects_stage", "projects", ["stage"])

    op.create_table(
        "project_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_project_notes_project_id", "project_notes", ["project_id"])

    op.create_table(
        "project_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(280), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("task_state", sa.String(24), nullable=False, server_default="todo"),
        sa.Column("waiting_on", sa.String(180)),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_project_tasks_project_id", "project_tasks", ["project_id"])
    op.create_index("ix_project_tasks_due_date", "project_tasks", ["due_date"])
    op.create_index("ix_project_tasks_task_state", "project_tasks", ["task_state"])

    op.create_table(
        "project_colors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(180), nullable=False),
        sa.Column("color_code", sa.String(64), nullable=False),
        sa.Column("material", sa.String(180)),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_project_colors_project_id", "project_colors", ["project_id"])

    op.create_table(
        "project_measurements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_name", sa.String(180), nullable=False),
        sa.Column("label", sa.String(180), nullable=False),
        sa.Column("value", sa.String(80), nullable=False),
        sa.Column("unit", sa.String(24), nullable=False, server_default="cm"),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_project_measurements_project_id", "project_measurements", ["project_id"])
    op.create_index("ix_project_measurements_measured_on", "project_measurements", ["measured_on"])

    op.create_table(
        "project_visits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("purpose", sa.String(280), nullable=False),
        sa.Column("visit_state", sa.String(24), nullable=False, server_default="planned"),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_project_visits_project_id", "project_visits", ["project_id"])
    op.create_index("ix_project_visits_visit_date", "project_visits", ["visit_date"])
    op.create_index("ix_project_visits_visit_state", "project_visits", ["visit_state"])


def downgrade() -> None:
    for table in ("project_visits", "project_measurements", "project_colors", "project_tasks", "project_notes"):
        op.drop_table(table)
    op.drop_index("ix_projects_stage", table_name="projects")
    with op.batch_alter_table("projects") as batch:
        for column in ("next_step", "address", "accent_color", "progress_percent", "stage"):
            batch.drop_column(column)

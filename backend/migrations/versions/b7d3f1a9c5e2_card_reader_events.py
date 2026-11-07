"""card reader: employee cards and raw attendance events

Revision ID: b7d3f1a9c5e2
Revises: a5e2c7d9f1b3
Create Date: 2026-10-30 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d3f1a9c5e2"
down_revision: str | None = "a5e2c7d9f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")


def upgrade() -> None:
    op.create_table(
        "employee_cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "employee_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("card_uid", sa.String(32), nullable=False, unique=True),
        sa.Column("status", record_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_employee_cards_employee_id", "employee_cards", ["employee_id"])
    op.create_index("ix_employee_cards_status", "employee_cards", ["status"])
    op.create_table(
        "attendance_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_key", sa.String(120), nullable=False, unique=True),
        sa.Column("device_id", sa.String(60)),
        sa.Column("card_uid", sa.String(32), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(8)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "employee_id", sa.String(36), sa.ForeignKey("employees.id", ondelete="RESTRICT")
        ),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column(
            "work_log_id", sa.String(36), sa.ForeignKey("work_logs.id", ondelete="RESTRICT")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_attendance_events_state", "attendance_events", ["state"])
    op.create_index(
        "ix_attendance_event_employee_at", "attendance_events", ["employee_id", "event_at"]
    )
    op.create_index("ix_attendance_event_uid_at", "attendance_events", ["card_uid", "event_at"])


def downgrade() -> None:
    op.drop_table("attendance_events")
    op.drop_table("employee_cards")

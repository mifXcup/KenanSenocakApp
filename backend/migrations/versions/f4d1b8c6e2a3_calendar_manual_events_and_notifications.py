"""calendar manual events, occurrences, reminder preferences and notification deliveries

Revision ID: f4d1b8c6e2a3
Revises: e3c9a7b5d1f2
Create Date: 2026-10-30 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4d1b8c6e2a3"
down_revision: str | None = "e3c9a7b5d1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "calendar_manual_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date()),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("start_time", sa.String(5)),
        sa.Column("repeat_rule", sa.String(10), nullable=False, server_default="none"),
        sa.Column("repeat_until", sa.Date()),
        sa.Column("amount_kurus", sa.Integer()),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT")),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id", ondelete="RESTRICT")),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id", ondelete="RESTRICT")),
        sa.Column("supplier_id", sa.String(36), sa.ForeignKey("suppliers.id", ondelete="RESTRICT")),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_calendar_manual_events_event_type", "calendar_manual_events", ["event_type"])
    op.create_index("ix_calendar_manual_events_start_date", "calendar_manual_events", ["start_date"])
    op.create_index("ix_calendar_manual_events_status", "calendar_manual_events", ["status"])

    op.create_table(
        "calendar_event_occurrences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "manual_event_id",
            sa.String(36),
            sa.ForeignKey("calendar_manual_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("occurrence_state", sa.String(12), nullable=False),
        sa.Column("postponed_to", sa.Date()),
        sa.Column("note", sa.String(255)),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("manual_event_id", "occurrence_date", name="uq_calendar_occurrence"),
    )
    op.create_index(
        "ix_calendar_event_occurrences_manual_event_id",
        "calendar_event_occurrences",
        ["manual_event_id"],
    )

    op.create_table(
        "calendar_reminder_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(32), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("offsets_days", sa.String(40), nullable=False),
        *_timestamps(),
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("delivery_key", sa.String(300), nullable=False, unique=True),
        sa.Column("event_id", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(80), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("offset_days", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("delivered_on", sa.Date(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notification_deliveries_event_id", "notification_deliveries", ["event_id"])


def downgrade() -> None:
    for table in (
        "notification_deliveries",
        "calendar_reminder_preferences",
        "calendar_event_occurrences",
        "calendar_manual_events",
    ):
        op.drop_table(table)

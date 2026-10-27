"""work log statuses, overtime hours and application settings

Revision ID: d6f4a5b7c8e9
Revises: c5e3f4a6b7d8
Create Date: 2026-10-27 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6f4a5b7c8e9"
down_revision: str | None = "c5e3f4a6b7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_logs",
        sa.Column("work_status", sa.String(16), nullable=False, server_default="worked"),
    )
    op.add_column(
        "work_logs",
        sa.Column("normal_hours", sa.Numeric(5, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "work_logs",
        sa.Column("overtime_hours", sa.Numeric(5, 2), nullable=False, server_default="0"),
    )
    op.add_column("work_logs", sa.Column("calculated_amount_kurus", sa.Integer()))
    op.add_column("work_logs", sa.Column("manual_amount_kurus", sa.Integer()))
    op.create_index("ix_work_logs_work_status", "work_logs", ["work_status"])

    # Eski kayıtlar: süre normal saate, etkin tutar hesaplanan tutara taşınır. Tutarı eski günlük
    # ücret formülüyle üretilemeyen kayıtlar manuel tutar sayılır; böylece sonradan düzenlense bile
    # tarihsel maliyet kendiliğinden değişmez.
    op.execute("UPDATE work_logs SET normal_hours = hours, calculated_amount_kurus = amount_kurus")
    op.execute(
        "UPDATE work_logs SET manual_amount_kurus = amount_kurus "
        "WHERE NOT EXISTS (SELECT 1 FROM employees e WHERE e.id = work_logs.employee_id "
        "AND e.daily_rate_kurus IS NOT NULL "
        "AND CAST(ROUND(e.daily_rate_kurus * work_logs.hours / 8.0) AS INTEGER) "
        "= work_logs.amount_kurus)"
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_index("ix_work_logs_work_status", table_name="work_logs")
    with op.batch_alter_table("work_logs") as batch:
        for column in (
            "manual_amount_kurus",
            "calculated_amount_kurus",
            "overtime_hours",
            "normal_hours",
            "work_status",
        ):
            batch.drop_column(column)

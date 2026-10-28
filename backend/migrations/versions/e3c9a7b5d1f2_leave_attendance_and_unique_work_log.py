"""leave ledger, holidays, weekly plans, employee profile and unique active work log

Revision ID: e3c9a7b5d1f2
Revises: d2b8f6a1c4e7
Create Date: 2026-10-29 10:00:00
"""
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "e3c9a7b5d1f2"
down_revision: str | None = "d2b8f6a1c4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")
DEFAULT_LEAVE_TYPES = (
    ("annual", "Yıllık izin", "annual_leave", True),
    ("sick", "Raporlu", "sick_leave", False),
    ("other_paid", "Diğer ücretli izin", "paid_leave", False),
    ("unpaid", "Ücretsiz izin", "unpaid_leave", False),
    ("excused", "Mazeret izni", "excused_leave", False),
)


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def upgrade() -> None:
    for name, kind in (
        ("email", sa.String(180)),
        ("address", sa.Text()),
        ("skill", sa.String(120)),
        ("emergency_contact_name", sa.String(180)),
        ("emergency_contact_phone", sa.String(40)),
        ("emergency_contact_relation", sa.String(60)),
        ("payment_method", sa.String(24)),
        ("salary_day", sa.Integer()),
    ):
        op.add_column("employees", sa.Column(name, kind))

    op.create_table(
        "leave_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("work_status", sa.String(24), nullable=False),
        sa.Column("deducts_entitlement", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_leave_types_status", "leave_types", ["status"])

    op.create_table(
        "leave_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "employee_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "leave_type_id",
            sa.String(36),
            sa.ForeignKey("leave_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("day_part", sa.String(12), nullable=False, server_default="full"),
        sa.Column("hours_per_day", sa.Numeric(5, 2)),
        sa.Column("total_hours", sa.Numeric(8, 2)),
        sa.Column("request_state", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text()),
        sa.Column("decision_note", sa.String(255)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_leave_requests_employee_id", "leave_requests", ["employee_id"])
    op.create_index("ix_leave_request_employee_dates", "leave_requests", ["employee_id", "start_date"])
    op.create_index("ix_leave_requests_request_state", "leave_requests", ["request_state"])
    op.create_index("ix_leave_requests_status", "leave_requests", ["status"])

    op.create_table(
        "leave_ledger_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "employee_id",
            sa.String(36),
            sa.ForeignKey("employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "leave_type_id",
            sa.String(36),
            sa.ForeignKey("leave_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entry_type", sa.String(16), nullable=False),
        sa.Column("quantity_hours", sa.Numeric(8, 2), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        sa.Column("leave_request_id", sa.String(36), sa.ForeignKey("leave_requests.id")),
        sa.Column(
            "reversed_entry_id",
            sa.String(36),
            sa.ForeignKey("leave_ledger_entries.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("source", sa.String(12), nullable=False, server_default="manual"),
        sa.Column("note", sa.Text()),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_leave_ledger_employee_type", "leave_ledger_entries", ["employee_id", "leave_type_id"]
    )
    op.create_index("ix_leave_ledger_entries_entry_type", "leave_ledger_entries", ["entry_type"])
    op.create_index("ix_leave_ledger_entries_entry_date", "leave_ledger_entries", ["entry_date"])
    op.create_index(
        "ix_leave_ledger_entries_leave_request_id", "leave_ledger_entries", ["leave_request_id"]
    )
    op.create_index("ix_leave_ledger_entries_status", "leave_ledger_entries", ["status"])

    op.create_table(
        "public_holidays",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("is_half_day", sa.Boolean(), nullable=False),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_public_holidays_status", "public_holidays", ["status"])
    op.create_index(
        "uq_public_holiday_date_active",
        "public_holidays",
        ["holiday_date"],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "weekly_work_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id", ondelete="RESTRICT")),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("workdays", sa.String(7), nullable=False),
        sa.Column("note", sa.String(255)),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_weekly_plan_employee_from", "weekly_work_plans", ["employee_id", "effective_from"])
    op.create_index("ix_weekly_work_plans_status", "weekly_work_plans", ["status"])

    op.create_table(
        "work_log_duplicate_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("employee_id", sa.String(36), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("kept_work_log_id", sa.String(36), nullable=False),
        sa.Column("cancelled_work_log_id", sa.String(36), nullable=False),
        sa.Column("kept_amount_kurus", sa.Integer(), nullable=False),
        sa.Column("cancelled_amount_kurus", sa.Integer(), nullable=False),
        sa.Column("kept_work_status", sa.String(16), nullable=False),
        sa.Column("cancelled_work_status", sa.String(16), nullable=False),
        sa.Column("in_locked_period", sa.Boolean(), nullable=False),
        sa.Column("resolution", sa.String(40), nullable=False),
        sa.Column("detail", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_work_log_duplicate_reports_employee_id", "work_log_duplicate_reports", ["employee_id"]
    )
    op.create_index(
        "ix_work_log_duplicate_reports_work_date", "work_log_duplicate_reports", ["work_date"]
    )

    op.execute(
        "ALTER TABLE work_logs ADD COLUMN leave_request_id VARCHAR(36) "
        "REFERENCES leave_requests (id)"
    )
    op.add_column("work_logs", sa.Column("leave_hours", sa.Numeric(5, 2)))
    op.add_column(
        "work_logs",
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
    )
    op.create_index("ix_work_logs_leave_request_id", "work_logs", ["leave_request_id"])

    _seed_leave_types()
    _resolve_duplicate_work_logs()
    op.create_index(
        "uq_work_log_employee_day_active",
        "work_logs",
        ["employee_id", "work_date"],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )


def _seed_leave_types() -> None:
    stamp = _stamp()
    table = sa.table(
        "leave_types",
        *[
            sa.column(name)
            for name in (
                "id", "code", "name", "work_status", "deducts_entitlement", "is_system", "status",
                "created_at", "updated_at",
            )
        ],
    )
    op.bulk_insert(
        table,
        [
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ks-leave-type:{code}")),
                "code": code,
                "name": name,
                "work_status": work_status,
                "deducts_entitlement": deducts,
                "is_system": True,
                "status": "ACTIVE",
                "created_at": stamp,
                "updated_at": stamp,
            }
            for code, name, work_status, deducts in DEFAULT_LEAVE_TYPES
        ],
    )


def _resolve_duplicate_work_logs() -> None:
    """Aynı personel+gün için birden fazla aktif puantajı güvenle çözer; hiçbir kayıt silinmez.

    En eski kayıt (created_at, id) korunur; diğerleri CANCELLED yapılır (tutarları ve durumları
    work_log_duplicate_reports'ta saklanır, denetim kaydı yazılır, nota işaret düşülür).
    """
    bind = op.get_bind()
    stamp = _stamp()
    groups = bind.execute(
        sa.text(
            "SELECT employee_id, work_date FROM work_logs WHERE status = 'ACTIVE' "
            "GROUP BY employee_id, work_date HAVING COUNT(*) > 1 ORDER BY employee_id, work_date"
        )
    ).all()
    for employee_id, work_date in groups:
        day = str(work_date)[:10]
        rows = bind.execute(
            sa.text(
                "SELECT id, amount_kurus, work_status FROM work_logs WHERE employee_id = :e "
                "AND work_date = :d AND status = 'ACTIVE' ORDER BY created_at, id"
            ),
            {"e": employee_id, "d": day},
        ).all()
        locked = bind.execute(
            sa.text(
                "SELECT 1 FROM payroll_periods WHERE status = 'ACTIVE' AND state IN "
                "('finalized', 'closed') AND period_start <= :d AND period_end >= :d LIMIT 1"
            ),
            {"d": day},
        ).first() is not None
        kept = rows[0]
        for loser in rows[1:]:
            detail = {
                "rule": "oldest_created_kept",
                "kept_work_log_id": kept[0],
                "group_size": len(rows),
                "amount_difference_kurus": loser[1],
            }
            bind.execute(
                sa.text(
                    "UPDATE work_logs SET status = 'CANCELLED', note = COALESCE(note || ' | ', '') "
                    "|| :mark WHERE id = :id"
                ),
                {"mark": f"Migration: mükerrer puantaj iptal edildi (korunan: {kept[0]})", "id": loser[0]},
            )
            bind.execute(
                sa.text(
                    "INSERT INTO work_log_duplicate_reports (id, employee_id, work_date, "
                    "kept_work_log_id, cancelled_work_log_id, kept_amount_kurus, "
                    "cancelled_amount_kurus, kept_work_status, cancelled_work_status, "
                    "in_locked_period, resolution, detail, created_at) VALUES (:id, :e, :d, :k, :c, "
                    ":ka, :ca, :ks, :cs, :locked, :res, :detail, :ts)"
                ),
                {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ks-dup-report:{loser[0]}")),
                    "e": employee_id,
                    "d": day,
                    "k": kept[0],
                    "c": loser[0],
                    "ka": kept[1],
                    "ca": loser[1],
                    "ks": kept[2],
                    "cs": loser[2],
                    "locked": locked,
                    "res": "cancelled_newer_duplicate",
                    "detail": json.dumps(detail),
                    "ts": stamp,
                },
            )
            bind.execute(
                sa.text(
                    "INSERT INTO audit_logs (id, entity_type, entity_id, action, detail, actor, "
                    "created_at) VALUES (:id, 'work_log', :eid, 'cancelled_duplicate', :detail, "
                    "'migration', :ts)"
                ),
                {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ks-dup-audit:{loser[0]}")),
                    "eid": loser[0],
                    "detail": json.dumps({"kept_work_log_id": kept[0], "date": day}),
                    "ts": stamp,
                },
            )


def downgrade() -> None:
    op.drop_index("uq_work_log_employee_day_active", table_name="work_logs")
    op.drop_index("ix_work_logs_leave_request_id", table_name="work_logs")
    with op.batch_alter_table("work_logs") as batch:
        batch.drop_column("source")
        batch.drop_column("leave_hours")
        batch.drop_column("leave_request_id")
    for table in (
        "work_log_duplicate_reports",
        "weekly_work_plans",
        "public_holidays",
        "leave_ledger_entries",
        "leave_requests",
        "leave_types",
    ):
        op.drop_table(table)
    with op.batch_alter_table("employees") as batch:
        for name in (
            "salary_day", "payment_method", "emergency_contact_relation", "emergency_contact_phone",
            "emergency_contact_name", "skill", "address", "email",
        ):
            batch.drop_column(name)

"""customer cards, receivable ledger, project budgets, change orders, purchase lifecycle

Revision ID: c1a7e9d2b3f4
Revises: fb1db398215f
Create Date: 2026-10-28 09:00:00
"""
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "c1a7e9d2b3f4"
down_revision: str | None = "fb1db398215f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

record_status = sa.Enum("ACTIVE", "CANCELLED", "ARCHIVED", "REVERSED", name="recordstatus")
_TR_LOWER = str.maketrans({"İ": "i", "I": "ı"})


def _normalize(name: str) -> str:
    # ks_yonetim.customers.normalize_customer_name ile aynı kural (migration uygulama koduna bağlanmaz).
    return " ".join(name.split()).translate(_TR_LOWER).casefold()


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("normalized_name", sa.String(180), nullable=False),
        sa.Column("phone", sa.String(40)),
        sa.Column("address", sa.Text()),
        sa.Column("contact_person", sa.String(180)),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_customers_normalized_name", "customers", ["normalized_name"], unique=True)
    op.create_index("ix_customers_status", "customers", ["status"])

    # SQLite: boş varsayılanlı REFERENCES sütunu ALTER ile eklenebilir; tablo yeniden kurulmaz.
    op.execute("ALTER TABLE projects ADD COLUMN customer_id VARCHAR(36) REFERENCES customers (id)")
    op.create_index("ix_projects_customer_id", "projects", ["customer_id"])

    op.create_table(
        "project_change_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("change_state", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_note", sa.String(255)),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_project_change_orders_project_id", "project_change_orders", ["project_id"])
    op.create_index(
        "ix_project_change_orders_change_state", "project_change_orders", ["change_state"]
    )
    op.create_index("ix_project_change_orders_status", "project_change_orders", ["status"])

    op.create_table(
        "receivable_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "customer_id",
            sa.String(36),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT")),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_receivable_customer_due", "receivable_schedules", ["customer_id", "due_date"])
    op.create_index("ix_receivable_schedules_project_id", "receivable_schedules", ["project_id"])
    op.create_index("ix_receivable_schedules_due_date", "receivable_schedules", ["due_date"])
    op.create_index("ix_receivable_schedules_status", "receivable_schedules", ["status"])

    op.create_table(
        "customer_financial_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "customer_id",
            sa.String(36),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT")),
        sa.Column(
            "receivable_schedule_id",
            sa.String(36),
            sa.ForeignKey("receivable_schedules.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "change_order_id",
            sa.String(36),
            sa.ForeignKey("project_change_orders.id", ondelete="RESTRICT"),
        ),
        sa.Column("movement_date", sa.Date(), nullable=False),
        sa.Column("movement_type", sa.String(24), nullable=False),
        sa.Column("direction", sa.String(24), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "reversed_movement_id",
            sa.String(36),
            sa.ForeignKey("customer_financial_movements.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_cust_movement_customer_date",
        "customer_financial_movements",
        ["customer_id", "movement_date"],
    )
    op.create_index(
        "ix_cust_movement_project", "customer_financial_movements", ["project_id", "movement_type"]
    )
    op.create_index(
        "ix_customer_financial_movements_receivable_schedule_id",
        "customer_financial_movements",
        ["receivable_schedule_id"],
    )
    op.create_index(
        "ix_customer_financial_movements_change_order_id",
        "customer_financial_movements",
        ["change_order_id"],
    )
    op.create_index(
        "ix_customer_financial_movements_movement_date",
        "customer_financial_movements",
        ["movement_date"],
    )
    op.create_index(
        "ix_customer_financial_movements_movement_type",
        "customer_financial_movements",
        ["movement_type"],
    )
    op.create_index(
        "ix_customer_financial_movements_status", "customer_financial_movements", ["status"]
    )

    op.create_table(
        "project_budget_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("original_amount_kurus", sa.Integer(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_project_budget_lines_project_id", "project_budget_lines", ["project_id"])
    op.create_index("ix_project_budget_lines_category", "project_budget_lines", ["category"])
    op.create_index("ix_project_budget_lines_status", "project_budget_lines", ["status"])

    op.create_table(
        "project_budget_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "budget_line_id",
            sa.String(36),
            sa.ForeignKey("project_budget_lines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("previous_amount_kurus", sa.Integer()),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("budget_line_id", "revision_no", name="uq_budget_revision_no"),
    )
    op.create_index(
        "ix_project_budget_revisions_budget_line_id", "project_budget_revisions", ["budget_line_id"]
    )

    # Satın alma yaşam döngüsü: mevcut kayıtlar teslim alınmış (received) sayılır.
    op.add_column(
        "purchases",
        sa.Column("lifecycle_state", sa.String(24), nullable=False, server_default="received"),
    )
    op.add_column(
        "purchases", sa.Column("received_kurus", sa.Integer(), nullable=False, server_default="0")
    )
    op.execute("UPDATE purchases SET received_kurus = total_kurus WHERE status <> 'CANCELLED'")
    op.execute("UPDATE purchases SET lifecycle_state = 'cancelled' WHERE status = 'CANCELLED'")

    _link_existing_project_customers()


def _link_existing_project_customers() -> None:
    """Project.customer_name değerlerini normalize edip müşteri kartına bağlar; orijinal metin korunur."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, customer_name FROM projects ORDER BY created_at, id")
    ).all()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    cards: dict[str, dict] = {}
    links: list[tuple[str, str]] = []
    for project_id, customer_name in rows:
        normalized = _normalize(customer_name or "")
        if not normalized:
            continue
        card = cards.get(normalized)
        if card is None:
            card = {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"ks-customer:{normalized}")),
                "name": " ".join(customer_name.split()),
                "normalized_name": normalized,
                "status": "ACTIVE",
                "created_at": stamp,
                "updated_at": stamp,
            }
            cards[normalized] = card
        links.append((project_id, card["id"]))
    if cards:
        table = sa.table(
            "customers",
            *[
                sa.column(name)
                for name in ("id", "name", "normalized_name", "status", "created_at", "updated_at")
            ],
        )
        op.bulk_insert(table, list(cards.values()))
    for project_id, customer_id in links:
        bind.execute(
            sa.text("UPDATE projects SET customer_id = :cid WHERE id = :pid"),
            {"cid": customer_id, "pid": project_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("purchases") as batch:
        batch.drop_column("received_kurus")
        batch.drop_column("lifecycle_state")
    for table in (
        "project_budget_revisions",
        "project_budget_lines",
        "customer_financial_movements",
        "receivable_schedules",
        "project_change_orders",
    ):
        op.drop_table(table)
    op.drop_index("ix_projects_customer_id", table_name="projects")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("customer_id")
    op.drop_table("customers")

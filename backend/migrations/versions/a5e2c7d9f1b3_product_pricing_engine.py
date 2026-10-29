"""product quote history, cost factors and explainable pricing suggestions

Revision ID: a5e2c7d9f1b3
Revises: f4d1b8c6e2a3
Create Date: 2026-10-29 14:15:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5e2c7d9f1b3"
down_revision: str | None = "f4d1b8c6e2a3"
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
        "project_products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("product_type", sa.String(120), nullable=False),
        sa.Column("description", sa.String(280)),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit", sa.String(24), nullable=False),
        sa.Column("finish", sa.String(120)),
        sa.Column("hardware_level", sa.String(80)),
        sa.Column("complexity_percent", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("quote_date", sa.Date(), nullable=False),
        sa.Column("quoted_total_kurus", sa.Integer()),
        sa.Column("accepted_total_kurus", sa.Integer()),
        sa.Column("actual_cost_kurus", sa.Integer()),
        sa.Column("target_margin_percent", sa.Numeric(6, 2), nullable=False, server_default="25"),
        sa.Column("pricing_state", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("note", sa.Text()),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    for column in ("project_id", "product_type", "quote_date", "pricing_state", "status"):
        op.create_index(f"ix_project_products_{column}", "project_products", [column])

    op.create_table(
        "product_cost_factors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_product_id",
            sa.String(36),
            sa.ForeignKey("project_products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("factor_key", sa.String(80), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("material_id", sa.String(36), sa.ForeignKey("materials.id", ondelete="RESTRICT")),
        sa.Column("share_percent", sa.Numeric(6, 2), nullable=False),
        sa.Column("reference_unit_price_kurus", sa.Integer(), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        *_timestamps(),
        sa.UniqueConstraint(
            "project_product_id", "factor_key", name="uq_product_cost_factor_key"
        ),
    )
    op.create_index(
        "ix_product_cost_factors_project_product_id",
        "product_cost_factors",
        ["project_product_id"],
    )
    op.create_index(
        "ix_product_cost_factors_material_id", "product_cost_factors", ["material_id"]
    )

    op.create_table(
        "pricing_index_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("factor_key", sa.String(80), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("material_id", sa.String(36), sa.ForeignKey("materials.id", ondelete="RESTRICT")),
        sa.Column("recorded_on", sa.Date(), nullable=False),
        sa.Column("unit_price_kurus", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(280)),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("status", record_status, nullable=False),
        *_timestamps(),
    )
    for column in ("factor_key", "material_id", "recorded_on", "status"):
        op.create_index(f"ix_pricing_index_entries_{column}", "pricing_index_entries", [column])

    op.create_table(
        "pricing_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_product_id",
            sa.String(36),
            sa.ForeignKey("project_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("suggested_low_kurus", sa.Integer(), nullable=False),
        sa.Column("suggested_mid_kurus", sa.Integer(), nullable=False),
        sa.Column("suggested_high_kurus", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.String(12), nullable=False),
        sa.Column("comparable_count", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_pricing_suggestions_project_product_id",
        "pricing_suggestions",
        ["project_product_id"],
    )
    op.create_index("ix_pricing_suggestions_created_at", "pricing_suggestions", ["created_at"])


def downgrade() -> None:
    op.drop_table("pricing_suggestions")
    op.drop_table("pricing_index_entries")
    op.drop_table("product_cost_factors")
    op.drop_table("project_products")

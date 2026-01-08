"""create model_run table

Revision ID: 20250128_create_model_run
Revises: 20251227_add_wape_adjusted
Create Date: 2025-01-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite


revision: str = "20250128_create_model_run"
down_revision: Union[str, Sequence[str], None] = "20251227_add_wape_adjusted"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create model_runs table."""
    op.create_table(
        "model_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(datetime('now'))"), nullable=False),
        sa.Column("model_type", sa.String(), nullable=False),
        sa.Column("selected_model_type", sa.String(), nullable=False),
        sa.Column("hyperparameters_json", sa.JSON(), nullable=True),
        sa.Column("training_window_end", sa.Date(), nullable=True),
        sa.Column("feature_version", sa.String(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_best", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("forecast_model_override_reason", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_model_runs_id"), "model_runs", ["id"], unique=False)
    op.create_index(op.f("ix_model_runs_product_id"), "model_runs", ["product_id"], unique=False)


def downgrade() -> None:
    """Drop model_runs table."""
    op.drop_index(op.f("ix_model_runs_product_id"), table_name="model_runs")
    op.drop_index(op.f("ix_model_runs_id"), table_name="model_runs")
    op.drop_table("model_runs")





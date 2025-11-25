"""Add forecast_metrics table"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250101_01"
down_revision: Union[str, Sequence[str], None] = "5bbc01878942"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "forecast_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("mape", sa.Float(), nullable=True),
        sa.Column("rmse", sa.Float(), nullable=True),
        sa.Column("n_points", sa.Integer(), nullable=False),
        sa.Column("model_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="ok"),
        sa.Column(
            "last_trained_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id"),
    )
    op.create_index(
        op.f("ix_forecast_metrics_id"),
        "forecast_metrics",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_forecast_metrics_product_id"),
        "forecast_metrics",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_forecast_metrics_product_id"), table_name="forecast_metrics")
    op.drop_index(op.f("ix_forecast_metrics_id"), table_name="forecast_metrics")
    op.drop_table("forecast_metrics")


"""add wape column to forecast_metrics

Revision ID: 20250127_add_wape
Revises: 20250116_add_stockout_cost_ratio
Create Date: 2025-01-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250127_add_wape"
down_revision: Union[str, Sequence[str], None] = "20250116_add_stockout_cost_ratio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add wape column to forecast_metrics table."""
    op.add_column(
        "forecast_metrics",
        sa.Column(
            "wape",
            sa.Float(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Drop wape column from forecast_metrics."""
    op.drop_column("forecast_metrics", "wape")



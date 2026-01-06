"""add wape_adjusted column to forecast_metrics

Revision ID: 20251227_add_wape_adjusted
Revises: 20251202_add_walk_forward_results
Create Date: 2025-12-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251227_add_wape_adjusted"
down_revision: Union[str, Sequence[str], None] = "20251202_add_walk_forward_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add wape_adjusted column to forecast_metrics table."""
    op.add_column(
        "forecast_metrics",
        sa.Column(
            "wape_adjusted",
            sa.Float(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Drop wape_adjusted column from forecast_metrics."""
    op.drop_column("forecast_metrics", "wape_adjusted")




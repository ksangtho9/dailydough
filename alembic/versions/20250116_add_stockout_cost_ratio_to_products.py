"""add stockout_cost_ratio column to products

Revision ID: 20250116_add_stockout_cost_ratio
Revises: 20251201_add_shelf_life
Create Date: 2025-01-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250116_add_stockout_cost_ratio"
down_revision: Union[str, Sequence[str], None] = "20250115_add_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add stockout_cost_ratio to products (default 2.0, meaning stockouts cost 2x waste)."""
    op.add_column(
        "products",
        sa.Column(
            "stockout_cost_ratio",
            sa.Float(),
            nullable=False,
            server_default="2.0",
        ),
    )


def downgrade() -> None:
    """Drop stockout_cost_ratio from products."""
    op.drop_column("products", "stockout_cost_ratio")


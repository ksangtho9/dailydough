"""add shelf_life_days column to products

Revision ID: 20251201_add_shelf_life
Revises: 20251129_add_price_cost
Create Date: 2025-12-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251201_add_shelf_life"
down_revision: Union[str, Sequence[str], None] = "20251129_add_price_cost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add shelf_life_days to products (1–2 days, default 1)."""
    op.add_column(
        "products",
        sa.Column(
            "shelf_life_days",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    """Drop shelf_life_days from products."""
    op.drop_column("products", "shelf_life_days")











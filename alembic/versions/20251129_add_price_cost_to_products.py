"""add price and cost_per_unit columns to products"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251129_add_price_cost"
down_revision: Union[str, Sequence[str], None] = "20251129_add_quantity_delivered"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("price", sa.Float(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("cost_per_unit", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "cost_per_unit")
    op.drop_column("products", "price")








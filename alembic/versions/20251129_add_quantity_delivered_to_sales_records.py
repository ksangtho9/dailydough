"""add quantity_delivered column to sales_records"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251129_add_quantity_delivered"
down_revision: Union[str, Sequence[str], None] = "20250217_add_timezone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sales_records",
        sa.Column("quantity_delivered", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sales_records", "quantity_delivered")



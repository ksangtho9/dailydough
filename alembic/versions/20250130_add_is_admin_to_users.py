"""add is_admin column to users

Revision ID: 20250130_add_is_admin
Revises: 20251227_add_wape_adjusted
Create Date: 2025-01-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250130_add_is_admin"
down_revision: Union[str, Sequence[str], None] = "20251227_add_wape_adjusted"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_admin column to users table."""
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Drop is_admin column from users table."""
    op.drop_column("users", "is_admin")

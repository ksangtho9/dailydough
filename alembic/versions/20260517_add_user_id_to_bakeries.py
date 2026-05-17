"""add user_id to bakeries

Revision ID: 20260517_add_user_id_to_bakeries
Revises: 20251227_add_wape_adjusted
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260517_add_user_id_to_bakeries"
down_revision: Union[str, Sequence[str], None] = "20251227_add_wape_adjusted"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bakeries", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index("ix_bakeries_user_id", "bakeries", ["user_id"])
    op.create_foreign_key(
        "fk_bakeries_user_id",
        "bakeries",
        "users",
        ["user_id"],
        ["id"],
    )

    # Assign all existing bakeries to the first admin user so data isn't orphaned.
    op.execute(
        """
        UPDATE bakeries
        SET user_id = (SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1)
        WHERE user_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_bakeries_user_id", "bakeries", type_="foreignkey")
    op.drop_index("ix_bakeries_user_id", table_name="bakeries")
    op.drop_column("bakeries", "user_id")

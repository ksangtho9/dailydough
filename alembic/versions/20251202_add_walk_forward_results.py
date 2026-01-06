"""add walk_forward_results table

Revision ID: 20251202_add_walk_forward_results
Revises: 20251201_add_shelf_life
Create Date: 2025-12-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20251202_add_walk_forward_results"
down_revision: Union[str, Sequence[str], None] = "20251201_add_shelf_life"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add walk_forward_results table for walk-forward validation."""
    op.create_table(
        "walk_forward_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("test_date", sa.Date(), nullable=False),
        sa.Column("predicted_quantity", sa.Float(), nullable=False),
        sa.Column("actual_quantity", sa.Float(), nullable=True),
        sa.Column("absolute_error", sa.Float(), nullable=True),
        sa.Column("percentage_error", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_walk_forward_results_id"),
        "walk_forward_results",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_walk_forward_results_product_id"),
        "walk_forward_results",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_walk_forward_results_test_date"),
        "walk_forward_results",
        ["test_date"],
        unique=False,
    )


def downgrade() -> None:
    """Drop walk_forward_results table."""
    op.drop_index(op.f("ix_walk_forward_results_test_date"), table_name="walk_forward_results")
    op.drop_index(op.f("ix_walk_forward_results_product_id"), table_name="walk_forward_results")
    op.drop_index(op.f("ix_walk_forward_results_id"), table_name="walk_forward_results")
    op.drop_table("walk_forward_results")







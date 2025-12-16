"""add events promotions weather tables

Revision ID: 20250115_add_features
Revises: 20251201_add_shelf_life
Create Date: 2025-01-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20250115_add_features"
down_revision: Union[str, Sequence[str], None] = "20251201_add_shelf_life"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add events, promotions, and weather_data tables."""
    # Events table
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bakery_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("recurrence_pattern", sa.String(), nullable=True),
        sa.Column("sales_multiplier", sa.String(), nullable=True, server_default="1.0"),
        sa.Column("description", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["bakery_id"], ["bakeries.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_id"), "events", ["id"], unique=False)
    op.create_index(op.f("ix_events_bakery_id"), "events", ["bakery_id"], unique=False)
    op.create_index(op.f("ix_events_date"), "events", ["date"], unique=False)

    # Promotions table
    op.create_table(
        "promotions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bakery_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("discount_percent", sa.Float(), nullable=True),
        sa.Column("sales_multiplier", sa.Float(), nullable=True, server_default="1.0"),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["bakery_id"], ["bakeries.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_promotions_id"), "promotions", ["id"], unique=False)
    op.create_index(op.f("ix_promotions_bakery_id"), "promotions", ["bakery_id"], unique=False)
    op.create_index(op.f("ix_promotions_product_id"), "promotions", ["product_id"], unique=False)
    op.create_index(op.f("ix_promotions_start_date"), "promotions", ["start_date"], unique=False)
    op.create_index(op.f("ix_promotions_end_date"), "promotions", ["end_date"], unique=False)

    # Weather data table
    op.create_table(
        "weather_data",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bakery_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("precipitation", sa.Float(), nullable=True),
        sa.Column("condition", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("is_forecast", sa.String(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["bakery_id"], ["bakeries.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_weather_data_id"), "weather_data", ["id"], unique=False)
    op.create_index(op.f("ix_weather_data_bakery_id"), "weather_data", ["bakery_id"], unique=False)
    op.create_index(op.f("ix_weather_data_date"), "weather_data", ["date"], unique=False)


def downgrade() -> None:
    """Drop events, promotions, and weather_data tables."""
    op.drop_index(op.f("ix_weather_data_date"), table_name="weather_data")
    op.drop_index(op.f("ix_weather_data_bakery_id"), table_name="weather_data")
    op.drop_index(op.f("ix_weather_data_id"), table_name="weather_data")
    op.drop_table("weather_data")

    op.drop_index(op.f("ix_promotions_end_date"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_start_date"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_product_id"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_bakery_id"), table_name="promotions")
    op.drop_index(op.f("ix_promotions_id"), table_name="promotions")
    op.drop_table("promotions")

    op.drop_index(op.f("ix_events_date"), table_name="events")
    op.drop_index(op.f("ix_events_bakery_id"), table_name="events")
    op.drop_index(op.f("ix_events_id"), table_name="events")
    op.drop_table("events")



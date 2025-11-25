"""add timezone column to bakeries"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20250217_add_timezone"
down_revision: Union[str, Sequence[str], None] = "20250101_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("bakeries")}

    if "timezone" not in columns:
        op.add_column(
            "bakeries",
            sa.Column(
                "timezone",
                sa.String(),
                nullable=True,
                server_default="UTC",
            ),
        )
        columns.add("timezone")

    if "timezone" in columns:
        op.execute(
            sa.text(
                "UPDATE bakeries SET timezone = 'UTC' WHERE timezone IS NULL"
            )
        )

        if bind.dialect.name != "sqlite":
            op.alter_column("bakeries", "timezone", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("bakeries")}
    if "timezone" in columns:
        op.drop_column("bakeries", "timezone")


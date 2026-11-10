"""activity fuel

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-10 13:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activity_fuel",
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.Column("fluid_ml", sa.Float(), nullable=True),
        sa.Column("gut", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("activity_id"),
    )


def downgrade() -> None:
    op.drop_table("activity_fuel")

"""unavailable period

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-10 15:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "unavailable_period",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("first_day", sa.Date(), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_unavailable_period_first_day"), "unavailable_period", ["first_day"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_unavailable_period_first_day"), table_name="unavailable_period")
    op.drop_table("unavailable_period")

"""activity rating

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-10 11:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activity_rating",
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("effort", sa.Integer(), nullable=True),
        sa.Column("legs", sa.Integer(), nullable=True),
        sa.Column("pain", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("activity_id"),
    )


def downgrade() -> None:
    op.drop_table("activity_rating")

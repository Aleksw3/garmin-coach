"""season outline

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-10 10:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "season_week",
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("hours", sa.Float(), nullable=False),
        sa.Column("climb_m", sa.Float(), nullable=True),
        sa.Column("longest_h", sa.Float(), nullable=True),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["goal_id"], ["goal.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("week_start"),
    )


def downgrade() -> None:
    op.drop_table("season_week")

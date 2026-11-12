"""descents

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-12 10:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, Sequence[str], None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "descent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("length_m", sa.Float(), nullable=False),
        sa.Column("drop_m", sa.Float(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_descent_activity_id", "descent", ["activity_id"])
    # A batch operation rebuilds the activity table for a Boolean column, and dropping the old
    # table deletes every row that refers to an activity. A plain ADD COLUMN leaves them alone.
    op.add_column(
        "activity",
        sa.Column("descents_scanned", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("activity", "descents_scanned")
    op.drop_index("ix_descent_activity_id", table_name="descent")
    op.drop_table("descent")

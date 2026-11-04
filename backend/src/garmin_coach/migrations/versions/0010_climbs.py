"""climbs

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-04 09:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "climb",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("start_lat", sa.Float(), nullable=False),
        sa.Column("start_lon", sa.Float(), nullable=False),
        sa.Column("length_m", sa.Float(), nullable=False),
        sa.Column("gain_m", sa.Float(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("track", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("climb", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_climb_activity_id"), ["activity_id"], unique=False)

    with op.batch_alter_table("activity", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("climbs_scanned", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("activity", schema=None) as batch_op:
        batch_op.drop_column("climbs_scanned")

    with op.batch_alter_table("climb", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_climb_activity_id"))

    op.drop_table("climb")

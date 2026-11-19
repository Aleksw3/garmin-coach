"""elevation override

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-19 11:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A plain ADD COLUMN, because a batch operation can rebuild the activity table, and dropping
    # the old table deletes every row that refers to an activity.
    op.add_column("activity", sa.Column("elevation_gain_override_m", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("activity", "elevation_gain_override_m")

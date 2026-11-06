"""sessions on the watch

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-06 21:30:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("planned_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("garmin_workout_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("garmin_schedule_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("sent_to_watch_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("planned_session", schema=None) as batch_op:
        batch_op.drop_column("sent_to_watch_at")
        batch_op.drop_column("garmin_schedule_id")
        batch_op.drop_column("garmin_workout_id")

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
    with op.batch_alter_table("activity") as batch:
        batch.add_column(sa.Column("elevation_gain_override_m", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("activity") as batch:
        batch.drop_column("elevation_gain_override_m")

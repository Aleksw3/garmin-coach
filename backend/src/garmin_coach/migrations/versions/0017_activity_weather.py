"""activity weather

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-10 14:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("temperature_c", "feels_like_c", "humidity_pct")


def upgrade() -> None:
    with op.batch_alter_table("activity") as batch:
        for column in COLUMNS:
            batch.add_column(sa.Column(column, sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("activity") as batch:
        for column in COLUMNS:
            batch.drop_column(column)

"""skipped prompt

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-19 12:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, Sequence[str], None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skipped_prompt",
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("activity_id", "kind"),
    )


def downgrade() -> None:
    op.drop_table("skipped_prompt")

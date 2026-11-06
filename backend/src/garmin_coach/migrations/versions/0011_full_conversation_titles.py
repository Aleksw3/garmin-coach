"""full conversation titles

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-06 20:40:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TITLE_LENGTH = 200


def upgrade() -> None:
    connection = op.get_bind()
    shortened = connection.execute(
        sa.text(
            "SELECT c.id, ("
            "  SELECT m.display_text FROM message m"
            "  WHERE m.conversation_id = c.id AND m.source = 'user'"
            "  AND m.display_text IS NOT NULL ORDER BY m.id LIMIT 1"
            ") FROM conversation c WHERE c.kind = 'chat' AND c.title LIKE '%...'"
        )
    ).all()
    for conversation_id, first_message in shortened:
        lines = (first_message or "").strip().splitlines()
        if lines:
            connection.execute(
                sa.text("UPDATE conversation SET title = :title WHERE id = :id"),
                {"title": lines[0][:TITLE_LENGTH], "id": conversation_id},
            )


def downgrade() -> None:
    pass

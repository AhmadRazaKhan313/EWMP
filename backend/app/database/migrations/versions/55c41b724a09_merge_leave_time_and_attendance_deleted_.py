"""merge leave time and attendance deleted_at

Revision ID: 55c41b724a09
Revises: b7d4f1a92c63, c4d8f1a6b3e7
Create Date: 2026-09-22 12:18:20.592388

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55c41b724a09'
down_revision: Union[str, None] = ('b7d4f1a92c63', 'c4d8f1a6b3e7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

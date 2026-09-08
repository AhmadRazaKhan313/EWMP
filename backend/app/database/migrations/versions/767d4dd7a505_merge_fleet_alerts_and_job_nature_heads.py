"""merge fleet-alerts and job_nature heads

Revision ID: 767d4dd7a505
Revises: 738c278f56fc, ebe9ce81bf8e
Create Date: 2026-09-05 10:50:46.909061

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '767d4dd7a505'
down_revision: Union[str, None] = ('738c278f56fc', 'ebe9ce81bf8e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

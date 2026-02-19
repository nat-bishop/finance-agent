"""Add strategy column to recommendation_groups.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recommendation_groups") as batch_op:
        batch_op.add_column(sa.Column("strategy", sa.Text(), server_default="bracket"))


def downgrade() -> None:
    with op.batch_alter_table("recommendation_groups") as batch_op:
        batch_op.drop_column("strategy")

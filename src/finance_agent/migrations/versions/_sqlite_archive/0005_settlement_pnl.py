"""Add settlement tracking to recommendation legs and hypothetical P&L to groups.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recommendation_legs") as batch_op:
        batch_op.add_column(sa.Column("settlement_value", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("settled_at", sa.Text(), nullable=True))

    with op.batch_alter_table("recommendation_groups") as batch_op:
        batch_op.add_column(sa.Column("hypothetical_pnl_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recommendation_legs") as batch_op:
        batch_op.drop_column("settled_at")
        batch_op.drop_column("settlement_value")

    with op.batch_alter_table("recommendation_groups") as batch_op:
        batch_op.drop_column("hypothetical_pnl_usd")

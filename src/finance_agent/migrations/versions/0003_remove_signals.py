"""Remove signals table and signal_id from recommendation_groups.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("signals")

    with op.batch_alter_table("recommendation_groups") as batch_op:
        batch_op.drop_column("signal_id")


def downgrade() -> None:
    with op.batch_alter_table("recommendation_groups") as batch_op:
        batch_op.add_column(sa.Column("signal_id", sa.Integer(), nullable=True))

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("generated_at", sa.Text(), nullable=False),
        sa.Column("scan_type", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), server_default="kalshi"),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("event_ticker", sa.Text()),
        sa.Column("signal_strength", sa.Float()),
        sa.Column("estimated_edge_pct", sa.Float()),
        sa.Column("details_json", sa.Text()),
        sa.Column("status", sa.Text(), server_default="pending"),
        sa.Column("acted_at", sa.Text()),
        sa.Column("session_id", sa.Text()),
    )

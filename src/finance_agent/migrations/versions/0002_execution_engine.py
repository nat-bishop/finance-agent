"""Add execution engine fields: auto-sizing, fees, fill tracking.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── recommendation_groups: add auto-sizing and computed fields ──
    with op.batch_alter_table("recommendation_groups") as batch_op:
        batch_op.add_column(sa.Column("total_exposure_usd", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("computed_edge_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("computed_fees_usd", sa.Float(), nullable=True))

    # ── recommendation_legs: make agent-supplied fields nullable, add execution fields ──
    with op.batch_alter_table("recommendation_legs") as batch_op:
        # Make previously NOT NULL fields nullable (code now computes these)
        batch_op.alter_column("action", existing_type=sa.Text(), nullable=True)
        batch_op.alter_column("side", existing_type=sa.Text(), nullable=True)
        batch_op.alter_column("quantity", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("price_cents", existing_type=sa.Integer(), nullable=True)
        # Add execution engine fields
        batch_op.add_column(sa.Column("is_maker", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("fill_price_cents", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("fill_quantity", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("orderbook_snapshot_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recommendation_legs") as batch_op:
        batch_op.drop_column("orderbook_snapshot_json")
        batch_op.drop_column("fill_quantity")
        batch_op.drop_column("fill_price_cents")
        batch_op.drop_column("is_maker")
        batch_op.alter_column("price_cents", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("quantity", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("side", existing_type=sa.Text(), nullable=False)
        batch_op.alter_column("action", existing_type=sa.Text(), nullable=False)

    with op.batch_alter_table("recommendation_groups") as batch_op:
        batch_op.drop_column("computed_fees_usd")
        batch_op.drop_column("computed_edge_pct")
        batch_op.drop_column("total_exposure_usd")

"""Drop dead columns from sessions table.

ended_at, summary, trades_placed, recommendations_made, pnl_usd were
either never populated or unreliable.  Rec/trade counts are now derived
via JOINs in get_sessions().

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_index("idx_sessions_ended_at")
        batch_op.drop_column("ended_at")
        batch_op.drop_column("summary")
        batch_op.drop_column("trades_placed")
        batch_op.drop_column("recommendations_made")
        batch_op.drop_column("pnl_usd")


def downgrade() -> None:
    import sqlalchemy as sa

    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("pnl_usd", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("recommendations_made", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("trades_placed", sa.Integer(), server_default="0"))
        batch_op.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ended_at", sa.Text(), nullable=True))
        batch_op.create_index("idx_sessions_ended_at", ["ended_at"])

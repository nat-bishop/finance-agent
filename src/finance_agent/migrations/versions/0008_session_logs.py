"""Add session_logs table for server-side session summaries.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS session_log_id_seq")

    op.create_table(
        "session_logs",
        sa.Column(
            "id",
            sa.Integer,
            sa.Sequence("session_log_id_seq"),
            primary_key=True,
            server_default=sa.text("nextval('session_log_id_seq')"),
        ),
        sa.Column("session_id", sa.Text, sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
    )
    op.create_index("idx_session_log_session", "session_logs", ["session_id"])


def downgrade() -> None:
    op.drop_index("idx_session_log_session")
    op.drop_table("session_logs")
    op.execute("DROP SEQUENCE IF EXISTS session_log_id_seq")

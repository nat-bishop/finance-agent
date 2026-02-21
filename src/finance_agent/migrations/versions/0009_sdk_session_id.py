"""Add sdk_session_id column to sessions table for resume capability.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sessions ADD COLUMN sdk_session_id TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN sdk_session_id")

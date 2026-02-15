"""Drop profile column from sessions table.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN profile")


def downgrade() -> None:
    op.execute("ALTER TABLE sessions ADD COLUMN profile TEXT")

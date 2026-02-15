"""Add recommendations table and sessions.recommendations_made column.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            group_id TEXT,
            leg_index INTEGER DEFAULT 0,
            exchange TEXT NOT NULL,
            market_id TEXT NOT NULL,
            market_title TEXT,
            action TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price_cents INTEGER NOT NULL,
            order_type TEXT DEFAULT 'limit',
            thesis TEXT,
            signal_id INTEGER,
            estimated_edge_pct REAL,
            kelly_fraction REAL,
            confidence TEXT,
            equivalence_notes TEXT,
            status TEXT DEFAULT 'pending',
            reviewed_at TEXT,
            executed_at TEXT,
            order_id TEXT,
            expires_at TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_rec_status ON recommendations(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_rec_group ON recommendations(group_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_rec_session ON recommendations(session_id)")
    op.execute("ALTER TABLE sessions ADD COLUMN recommendations_made INTEGER DEFAULT 0")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recommendations")

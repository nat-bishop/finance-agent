"""Alembic environment — programmatic configuration, no alembic.ini needed."""

from alembic import context
from sqlalchemy import create_engine


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    url = context.config.get_main_option("sqlalchemy.url", "")
    engine = create_engine(url)

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()

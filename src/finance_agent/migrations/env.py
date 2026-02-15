"""Alembic environment — programmatic configuration with autogenerate support."""

from alembic import context
from sqlalchemy import create_engine

from finance_agent.models import Base


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    url = context.config.get_main_option("sqlalchemy.url", "")
    engine = create_engine(url)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()

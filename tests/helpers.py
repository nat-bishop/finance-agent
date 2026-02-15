"""Test-only helpers for raw SQL and ORM row access. NOT for production code."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from finance_agent.database import AgentDatabase


def raw_select(db: AgentDatabase, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Test-only: raw SQL for pragma/schema checks. Not for application data."""
    rewritten = sql
    param_dict: dict[str, Any] = {}
    for i, val in enumerate(params):
        rewritten = rewritten.replace("?", f":p{i}", 1)
        param_dict[f"p{i}"] = val
    with db._session_factory() as session:
        result = session.execute(text(rewritten), param_dict)
        return [dict(zip(list(result.keys()), row, strict=True)) for row in result.fetchall()]


def get_row(db: AgentDatabase, model_class: type, pk: Any) -> dict[str, Any] | None:
    """Test-only: fetch a single ORM row by primary key, returns dict."""
    with db._session_factory() as session:
        row = session.get(model_class, pk)
        return row.to_dict() if row else None

.PHONY: up up-fast down shell logs lint format test test-cov collect backfill backup startup nuke-db nuke-data

# ── Docker ───────────────────────────────────────────────────

up:
	@echo "Collecting market data (build runs in parallel)..."
	@uv run python -m finance_agent.collector & COLLECT_PID=$$!; docker compose build agent; wait $$COLLECT_PID
	docker compose run --rm agent

up-fast:
	docker compose run --rm agent

down:
	docker compose down --remove-orphans

shell:
	docker compose run --build --rm agent /bin/bash

N ?= 250
logs:
	@latest=$$(ls -t workspace/data/logs/agent_*.log 2>/dev/null | head -1); \
	if [ -n "$$latest" ]; then tail -$(N) "$$latest"; else echo "No session logs yet -- run make up first"; fi

# ── Code quality (local) ────────────────────────────────────

lint:
	uv run ruff check src/
	uv run ruff format --check src/
	uv run mypy src/

format:
	uv run ruff check --fix src/
	uv run ruff format src/

# ── Testing (local) ─────────────────────────────────────────

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov --cov-report=term-missing

# ── Data pipeline (local) ──────────────────────────────────

collect:
	uv run python -m finance_agent.collector

backfill:
	uv run python -m finance_agent.backfill

backup:
	uv run python -c "from finance_agent.database import run_backup; run_backup()"

migrate:
	uv run python scripts/migrate_sqlite_to_duckdb.py

startup:
	uv run python -c "from finance_agent.database import run_startup; run_startup()"

# ── Dangerous resets ────────────────────────────────────────

nuke-db:
	@echo "This will DELETE the database."
	@read -p "Continue? [y/N] " c && [ "$$c" = y ] || exit 1
	rm -f workspace/data/agent.duckdb workspace/data/agent.duckdb.wal
	@echo "Database deleted. Will be recreated on next run."

nuke-data:
	@echo "This will DELETE ALL workspace data."
	@read -p "Continue? [y/N] " c && [ "$$c" = y ] || exit 1
	rm -rf workspace/data/* workspace/analysis/*
	@echo "Workspace data cleared."

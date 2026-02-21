.PHONY: up down shell logs dev ui lint format test test-cov test-live collect backfill backfill-meta backup startup nuke-db nuke-data

# ── Docker (agent server) ─────────────────────────────────

up:
	docker compose build agent
	docker compose up -d

down:
	docker compose down --remove-orphans

shell:
	docker compose exec agent bash

N ?= 250
logs:
	docker compose logs -f agent

# ── Dev (local server) ────────────────────────────────────

dev:
	FA_WORKSPACE=workspace FA_LOG_DIR=workspace/logs uv run python -m finance_agent.server_main

# ── TUI (local) ───────────────────────────────────────────

ui:
	uv run python -m finance_agent.tui

# ── Code quality (local) ──────────────────────────────────

lint:
	uv run ruff check src/
	uv run ruff format --check src/
	uv run mypy src/

format:
	uv run ruff check --fix src/
	uv run ruff format src/

# ── Testing (local) ───────────────────────────────────────

test:
	uv run pytest tests/ -v -m "not live"

test-cov:
	uv run pytest tests/ -v -m "not live" --cov --cov-report=term-missing

test-live:
	uv run pytest tests/test_kalshi_live.py -v -m live

# ── Data pipeline (local) ────────────────────────────────

collect:
	uv run python -m finance_agent.collector

backfill:
	uv run python -m finance_agent.backfill

backfill-meta:  ## backfill metadata for historical tickers from Kalshi API
	uv run python -m finance_agent.meta_backfill $(ARGS)

backup:
	uv run python -c "from finance_agent.database import run_backup; run_backup()"

migrate:
	uv run python scripts/migrate_sqlite_to_duckdb.py

startup:
	uv run python -c "from finance_agent.database import run_startup; run_startup()"

# ── Dangerous resets ──────────────────────────────────────

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

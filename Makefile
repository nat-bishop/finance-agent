.PHONY: build run dev shell clean logs setup lock install lint format check collect signals scan backup

build:
	docker compose build

run:
	docker compose run --rm agent

dev:
	docker compose run --rm -v ./workspace:/workspace agent

shell:
	docker compose run --rm --entrypoint /bin/bash agent

clean:
	docker compose down -v

logs:
	@echo "Trade journal is now in SQLite. Use: make shell -> sqlite3 /workspace/data/agent.db"

setup:
	cp .env.example .env

lock:
	uv lock

install:
	uv sync

lint:
	uv run ruff check src/
	uv run ruff format --check src/
	uv run mypy src/

format:
	uv run ruff check --fix src/
	uv run ruff format src/

check: lint

# ── Data pipeline ────────────────────────────────────────────

collect:
	uv run python -m finance_agent.collector

signals:
	uv run python -m finance_agent.signals

scan: collect signals

backup:
	uv run python -c "from finance_agent.database import AgentDatabase; from finance_agent.config import load_configs; _, tc = load_configs(); db = AgentDatabase(tc.db_path); print(db.backup_if_needed(tc.backup_dir) or 'No backup needed'); db.close()"

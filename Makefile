.PHONY: build run dev shell clean logs setup lock install lint format check test test-cov collect signals scan backup startup

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
	@if [ -f workspace/data/agent.log ]; then tail -100 workspace/data/agent.log; else echo "No agent.log yet -- run make run first"; fi

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

# ── Testing ──────────────────────────────────────────────────
test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov --cov-report=term-missing

# ── Data pipeline ────────────────────────────────────────────

collect:
	uv run python -m finance_agent.collector

signals:
	uv run python -m finance_agent.signals

scan: collect signals

backup:
	uv run python -c "from finance_agent.database import AgentDatabase; from finance_agent.config import load_configs; _, _, tc = load_configs(); db = AgentDatabase(tc.db_path); print(db.backup_if_needed(tc.backup_dir) or 'No backup needed'); db.close()"

startup:
	uv run python -c "from finance_agent.config import load_configs; from finance_agent.database import AgentDatabase; import json; _, _, tc = load_configs(); db = AgentDatabase(tc.db_path); state = db.get_session_state(); print(json.dumps(state, indent=2, default=str)); db.close()"

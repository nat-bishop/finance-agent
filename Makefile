.PHONY: up down shell logs lint format test test-cov collect backup startup nuke-db nuke-data

# ── Docker ───────────────────────────────────────────────────

up:
	docker compose run --build --rm agent

down:
	docker compose down -v

shell:
	docker compose run --build --rm agent /bin/bash

logs:
	@if [ -f workspace/data/agent.log ]; then tail -100 workspace/data/agent.log; else echo "No agent.log yet -- run make up first"; fi

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

# ── Data pipeline (Docker) ──────────────────────────────────

collect:
	docker compose run --build --rm agent python -m finance_agent.collector

backup:
	docker compose run --build --rm agent python -c "from finance_agent.database import AgentDatabase; from finance_agent.config import load_configs; _, _, tc = load_configs(); db = AgentDatabase(tc.db_path); print(db.backup_if_needed(tc.backup_dir) or 'No backup needed'); db.close()"

startup:
	docker compose run --build --rm agent python -c "from finance_agent.config import load_configs; from finance_agent.database import AgentDatabase; import json; _, _, tc = load_configs(); db = AgentDatabase(tc.db_path); state = db.get_session_state(); print(json.dumps(state, indent=2, default=str)); db.close()"

# ── Dangerous resets ────────────────────────────────────────

nuke-db:
	@echo "This will stop containers and DELETE the database."
	@read -p "Continue? [y/N] " c && [ "$$c" = y ] || exit 1
	docker compose down
	docker compose run --rm agent rm -f /workspace/data/agent.db /workspace/data/agent.db-wal /workspace/data/agent.db-shm
	@echo "Database deleted. Will be recreated on next run."

nuke-data:
	@echo "This will stop containers and DELETE ALL workspace data."
	@read -p "Continue? [y/N] " c && [ "$$c" = y ] || exit 1
	docker compose down
	docker compose run --rm agent sh -c "rm -rf /workspace/data/* /workspace/analysis/* /workspace/backups/*"
	@echo "Workspace data cleared."

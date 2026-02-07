.PHONY: build run dev shell clean logs setup lock install lint format check

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
	cat workspace/trade_journal/trades.jsonl

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

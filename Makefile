.PHONY: build run dev shell clean logs setup lock install

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

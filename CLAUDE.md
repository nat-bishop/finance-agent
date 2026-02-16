# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Docker
make up             # build + run agent TUI in Docker
make down           # stop containers (workspace data preserved)
make shell          # bash into container
make logs           # tail the agent log file (workspace/data/agent.log)

# Data pipeline (Docker)
make collect        # snapshot market data + sync Kalshi daily history
make backup         # backup SQLite database
make startup        # dump session state JSON (debug)

# Code quality (local)
make lint           # ruff check + format check + mypy
make format         # ruff fix + format

# Testing (local)
make test           # run all tests
make test-cov       # run tests with coverage report

# Dangerous resets
make nuke-db        # delete database file (with confirmation)
make nuke-data      # delete all workspace data (with confirmation)
```

## Architecture

Kalshi market analysis system built on `claude-agent-sdk`. The agent runs as an interactive REPL inside a Docker container with a sandboxed `/workspace` filesystem. It discovers mispricings across Kalshi markets using code-first analysis (bracket arbitrage, correlations, category anomalies) and produces structured trade recommendations — it does not execute trades directly.

### Three-layer design

**Programmatic layer** (no LLM, runs separately):
- `collector.py` — snapshots Kalshi market data to SQLite, syncs daily history from S3, generates `/workspace/data/markets.jsonl` (one JSON object per market for agent programmatic discovery)
- Run via: `make collect`

**Agent layer** (Claude REPL, runs on demand):
- Writes Python scripts against `markets.jsonl` and SQLite for bulk market analysis
- Investigates opportunities using MCP tools for live market data (orderbooks, trades, portfolio)
- Two recommendation strategies: `bracket` (guaranteed arb, auto-computed) and `manual` (agent-specified correlated trades)
- Records trade recommendations via `recommend_trade` tool for separate review/execution
- Persists findings to `/workspace/analysis/knowledge_base.json` across sessions

**TUI layer** (Textual, runs the app):
- `tui/app.py` — FinanceApp: initializes clients, DB, SDK, registers 4 screens (F1-F4)
- `tui/services.py` — async wrappers bridging exchange clients to Textual event loop
- `tui/screens/` — dashboard (chat+sidebar), recommendations, portfolio, history
- `tui/widgets/` — 7 widgets: agent_chat, rec_card, rec_list, portfolio_panel, status_bar, ask_modal, confirm_modal

### Source -> Runtime boundary

Source code (`src/finance_agent/`) is installed into the Docker image at `/app` and is **not visible to the agent at runtime**. The agent only sees `/workspace`, which contains analysis scripts, data, and outputs.

### Module roles

- **main.py** — Assembles `ClaudeAgentOptions`, builds SDK options. Entry point calls TUI. Wires `setup_logging()`.
- **logging_config.py** — `setup_logging()` configures root logger with stderr console + optional file handler. Idempotent, quiets noisy libraries (alembic, sqlalchemy, urllib3).
- **config.py** — Three config classes: `Credentials(BaseSettings)` loads API keys from `.env`/env vars; `TradingConfig` and `AgentConfig` are plain dataclasses (edit source to change defaults). Key trading defaults: `kalshi_max_position_usd=100`, `min_edge_pct=7.0`, `recommendation_ttl_minutes=60`. Also loads and templates `prompts/system.md`.
- **models.py** — SQLAlchemy ORM models (`DeclarativeBase`, `mapped_column`). Canonical schema definition for all 8 tables. Alembic autogenerate reads these.
- **tools.py** — Unified MCP tool factories via `@tool` decorator. `create_market_tools(kalshi)` → 5 read-only tools, `create_db_tools(db, session_id, kalshi)` → 1 tool (`recommend_trade` with strategy + legs array). 6 tools total.
- **kalshi_client.py** — Thin wrapper around `kalshi_python_sync` SDK with rate limiting. Auth is RSA-PSS signing. Includes get_events (paginated).
- **polymarket_client.py** — Dormant module. Thin wrapper around `polymarket-us` SDK. Preserved for future re-enablement but not imported by active code.
- **fees.py** — Kalshi fee calculations: P(1-P) parabolic formula, `kalshi_fee()`, `leg_fee()`, `best_price_and_depth()`, `compute_arb_edge()`.
- **hooks.py** — Hooks using `HookMatcher`. Auto-approve reads, recommendation counting via PostToolUse, session end with watchlist reminder.
- **database.py** — `AgentDatabase` class wrapping SQLite (WAL mode). Alembic migrations auto-run on startup. Events table has composite PK `(event_ticker, exchange)`. `get_session_state()` returns last_session, unreconciled_trades. Recommendation groups+legs CRUD for frontend.
- **collector.py** — Standalone Kalshi data collector. Paginated event collection via `GET /events`. Generates `markets.jsonl` (one JSON object per market with denormalized event metadata). Also triggers incremental Kalshi daily history sync and upserts market metadata to `kalshi_market_meta`.
- **backfill.py** — Kalshi historical daily data sync from public S3 bucket. Dynamic: fetches only missing days (full backfill on empty DB, incremental on subsequent runs). Called by collector or standalone via `python -m finance_agent.backfill`.
- **rate_limiter.py** — Token-bucket rate limiter with separate read/write buckets.
- **api_base.py** — Base class for API clients with shared rate limiting and serialization.
- **prompts/system.md** — System prompt template: Kalshi market analyst, code-first analysis, two recommendation strategies (bracket + manual), risk rules, session management.

### Key patterns

- **Factory + closure** for tools: `create_market_tools(kalshi)` returns a list of `@tool`-decorated functions closed over the Kalshi client.
- **MCP tool naming**: `mcp__markets__{tool_name}`, `mcp__db__{tool_name}`. Two MCP servers, 6 tools total.
- **Conventions**: Prices in cents, action+side, exchange column always "kalshi" in active code.
- **Config**: `Credentials` loads from env vars/`.env`; `TradingConfig` and `AgentConfig` are source-level defaults.
- **Hook ordering**: catch-all auto-approve → PostToolUse rec audit → Stop session end.
- **Startup context injection**: `main.py` calls `db.get_session_state()` and injects result into `BEGIN_SESSION` message. Agent starts with full context — no tool call needed.
- **Watchlist**: `/workspace/data/watchlist.md` — markdown file the agent reads/writes directly (replaces former DB watchlist tools).
- **Analyst-only**: Agent recommends trades via `recommend_trade` DB tool. Exchange client methods remain for TUI executor.

### Logging

Centralized via `logging_config.py`. Call `setup_logging()` once per entry point; all other modules use `logger = logging.getLogger(__name__)` at module level.

**Where logs go:**
- **TUI app** (`make run` / `make dev`): stderr (visible in terminal) + `/workspace/data/agent.log` (persisted on host via Docker volume mount at `./workspace/data/agent.log`). View with `make logs`.
- **Collector** (`make collect`): stderr only (runs locally, not in Docker). Output visible in terminal, not saved to file.
- **Log levels**: INFO for normal operations, DEBUG for verbose (exception tracebacks in dashboard/portfolio refresh), WARNING for interrupts, ERROR for execution failures.
- **TUI display vs logging**: RichLog widgets show user-facing agent conversation. Python logging is a separate developer/ops channel — they don't overlap.

### Workspace scripts

`workspace/scripts/` contains analysis tools the agent runs inside the Docker container:
- `db_utils.py` — Shared SQLite query helpers
- `scan_brackets.py` — Bracket arb scanner (mutually exclusive events)
- `correlations.py` — Pairwise Pearson correlations within a category
- `query_history.py` — kalshi_daily history queries with titles
- `market_info.py` — Full market lookup across all tables
- `category_overview.py` — Category summary: market count, spreads, volume
- `schema_reference.md` — Database schema reference for the agent

`workspace/lib/` contains legacy reference scripts:
- `kelly_size.py` — Kelly criterion position sizing (legacy reference)

## Code style

- **Ruff** for linting and formatting (line length 99, Python 3.12 target)
- **mypy** for type checking (lenient: `ignore_missing_imports`, no strict mode)
- `workspace/` is excluded from linting (agent-authored scripts, not package code)
- Pre-commit hooks run ruff lint + format on every commit
- **SQLAlchemy ORM only** — all database queries must use ORM `select()`, `insert()`, `update()`, `delete()` on model classes. No raw SQL strings or `exec_driver_sql`. Add new query methods to `database.py` rather than writing inline SQL.

## Testing

- **pytest** + **pytest-asyncio** (asyncio_mode="auto"), **pytest-cov** for coverage
- `make test` runs all tests; `make test-cov` adds coverage report
- Tests live in `tests/` (core modules) and `tests/tui/` (TUI services, widgets, messages)
- Fixtures in `tests/conftest.py` (temp DB, mock Kalshi client, sample data factories) and `tests/tui/conftest.py` (TUIServices wired to mocks)
- TUI widget tests use Textual's `App.run_test()` / `Pilot` for headless rendering

## Documentation

- **README.md** — project overview, architecture, quickstart, tool reference, database schema, config guide. Keep in sync with CLAUDE.md when making architectural changes (screen counts, tool counts, table counts, removed features, etc.).

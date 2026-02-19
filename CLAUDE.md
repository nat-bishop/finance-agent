# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Docker
make up             # build + run agent TUI in Docker
make down           # stop containers (workspace data preserved)
make shell          # bash into container
make logs           # tail the agent log file (workspace/data/agent.log)

# Data pipeline (local)
make collect        # snapshot market data + sync Kalshi daily history
make backup         # backup DuckDB database
make startup        # dump session state JSON (debug)

# Code quality (local)
make lint           # ruff check + format check + mypy
make format         # ruff fix + format

# Testing (local)
make test           # run all tests
make test-cov       # run tests with coverage report

```

## Architecture

Kalshi market analysis system built on `claude-agent-sdk`. The agent runs as an interactive REPL inside a Docker container with a sandboxed `/workspace` filesystem. It discovers mispricings across Kalshi markets using a combination of programmatic analysis and semantic reasoning — reading settlement rules, understanding cross-market relationships, and writing custom analytical scripts. Produces structured trade recommendations — it does not execute trades directly.

### Three-layer design

**Programmatic layer** (no LLM, runs separately):
- `collector.py` — snapshots Kalshi market data to DuckDB, syncs daily history from S3
- Run via: `make collect`

**Agent layer** (Claude REPL, runs on demand):
- Queries canonical DuckDB views (`v_latest_markets`, `v_daily_with_meta`) for bulk market analysis
- Investigates opportunities using MCP tools for live market data (orderbooks, trades, portfolio)
- Records trade recommendations via `recommend_trade` tool for separate review/execution
- Persists findings to `/workspace/analysis/knowledge_base.md` across sessions

**TUI layer** (Textual, runs the app):
- `tui/app.py` — FinanceApp: initializes clients, DB, SDK, registers 4 screens (F1-F4)
- `tui/services.py` — async wrappers bridging exchange clients to Textual event loop
- `tui/screens/` — dashboard (chat+sidebar), recommendations, portfolio, history
- `tui/widgets/` — 8 widgets: agent_chat, rec_card, rec_list, portfolio_panel, kb_panel, status_bar, ask_modal, confirm_modal

### Source -> Runtime boundary

Source code (`src/finance_agent/`) is installed into the Docker image at `/app` and is **not visible to the agent at runtime**. The agent only sees `/workspace`.

**Workspace isolation** (dual-mount pattern):
- `workspace/scripts/` → COPY'd into image at `/workspace/scripts/` (read-only, immutable)
- `workspace/data/` → mounted `:ro` at `/workspace/data/` (kernel-enforced read-only for agent) + `:rw` at `/app/state/` (app code writes DB/logs here, outside agent sandbox)
- `workspace/analysis/` → mounted `:rw` at `/workspace/analysis/` (agent's writable scratch space)

The PreToolUse hook denies Write/Edit to protected paths with helpful messages. Bash writes to `:ro` paths fail at the kernel level.

### Module roles

- **main.py** — Assembles `ClaudeAgentOptions`, builds SDK options. Entry point loads config, wires `setup_logging()`, launches TUI.
- **logging_config.py** — `setup_logging()` configures root logger with stderr console + optional file handler. Idempotent, quiets noisy libraries (alembic, sqlalchemy, urllib3). `add_session_file_handler(log_dir, session_id)` adds a per-session file handler after session creation.
- **config.py** — Three config classes: `Credentials(BaseSettings)` loads API keys from `.env`/env vars; `TradingConfig` and `AgentConfig` are plain dataclasses (edit source to change defaults). Key trading defaults: `kalshi_max_position_usd=100`, `recommendation_ttl_minutes=60`. Path fields (`db_path`, `backup_dir`, `log_dir`) have env var overrides (`FA_DB_PATH`, `FA_BACKUP_DIR`, `FA_LOG_DIR`) set in `docker-compose.yml`. Also loads and templates `prompts/system.md`.
- **constants.py** — Shared string constants: exchange names (`EXCHANGE_KALSHI`), statuses (`STATUS_PENDING`, `STATUS_EXECUTED`, etc.), sides (`SIDE_YES`/`SIDE_NO`), actions (`ACTION_BUY`/`ACTION_SELL`), `STRATEGY_MANUAL`, `BINARY_PAYOUT_CENTS`. Imported across modules to avoid scattered magic strings.
- **models.py** — SQLAlchemy ORM models (`DeclarativeBase`, `mapped_column`) with DuckDB-compatible `Sequence` objects for auto-increment PKs. Canonical schema definition for all 8 tables. `UniqueConstraint` on `kalshi_daily(date, ticker_name)` for DuckDB `ON CONFLICT` support. Alembic autogenerate reads these.
- **tools.py** — Unified MCP tool factories via `@tool` decorator. `create_market_tools(kalshi)` → 5 read-only tools, `create_db_tools(db, session_id, kalshi)` → 1 tool (`recommend_trade` with thesis + legs array). 6 tools total.
- **kalshi_client.py** — Thin wrapper around `kalshi_python_sync` SDK with rate limiting. Auth is RSA-PSS signing. Includes get_events (paginated).
- **polymarket_client.py** — Dormant module. Thin wrapper around `polymarket-us` SDK. Preserved for future re-enablement but not imported by active code.
- **fees.py** — Kalshi fee calculations: P(1-P) parabolic formula, `kalshi_fee()`, `best_price_and_depth()`, `compute_hypothetical_pnl()`.
- **hooks.py** — Hooks using `HookMatcher`. Auto-approve with file protection (denies Write/Edit to read-only paths), recommendation counting via PostToolUse, session end DB recording.
- **database.py** — `AgentDatabase` class wrapping DuckDB via `duckdb_engine` SQLAlchemy dialect. Alembic migrations auto-run on startup. Creates 3 canonical views (`v_latest_markets`, `v_daily_with_meta`, `v_active_recommendations`) after migrations. Upserts use raw SQL `text()` with `ON CONFLICT` for DuckDB compatibility. `maintenance()` runs `CHECKPOINT` (and optionally `VACUUM ANALYZE`). Events table has composite PK `(event_ticker, exchange)`. `get_session_state()` returns last_session, unreconciled_trades. Recommendation groups+legs CRUD for frontend. `purge_old_daily(retention_days, min_ticker_days)` removes rows for short-lived expired tickers. `get_missing_meta_tickers()` prioritizes recently-seen tickers (last 90 days).
- **collector.py** — Standalone Kalshi data collector. Paginated event collection via `GET /events`. Triggers incremental Kalshi daily history sync, upserts market metadata to `kalshi_market_meta`, resolves settlements, and runs retention purges (`purge_old_snapshots`, `purge_old_daily`).
- **backfill.py** — Kalshi historical daily data sync from public S3 bucket. Dynamic: fetches only missing days (full backfill on empty DB, incremental on subsequent runs). Parallel S3 downloads (8 workers via ThreadPoolExecutor), serial DB inserts in date order for contiguous-prefix guarantee on interruption. Calls `db.maintenance()` after sync. `backfill_missing_meta()` fetches titles/categories for recent daily tickers missing from `kalshi_market_meta` (200/run, prioritizes recently-seen tickers). Called by collector or standalone via `python -m finance_agent.backfill`.
- **rate_limiter.py** — Token-bucket rate limiter with separate read/write buckets.
- **api_base.py** — Base class for API clients with shared rate limiting and serialization.
- **prompts/system.md** — System prompt template: Kalshi market analyst, prediction market mechanics education, investigative analysis approach, DuckDB query rules, SQL cheat sheet, risk rules, session management.

### Key patterns

- **Factory + closure** for tools: `create_market_tools(kalshi)` returns a list of `@tool`-decorated functions closed over the Kalshi client.
- **MCP tool naming**: `mcp__markets__{tool_name}`, `mcp__db__{tool_name}`. Two MCP servers, 6 tools total.
- **Conventions**: Prices in cents, action+side, exchange column always "kalshi" in active code. Domain strings (`"kalshi"`, `"pending"`, `"yes"`, `"buy"`, `"manual"`, etc.) defined in `constants.py` — import from there, don't hardcode.
- **Config**: `Credentials` loads from env vars/`.env`; `TradingConfig` and `AgentConfig` are source-level defaults. Path fields on TradingConfig have `FA_*` env var overrides for Docker.
- **Hook ordering**: PreToolUse (auto-approve + file protection) → PostToolUse rec audit → Stop session end.
- **Startup context injection**: `app.py` calls `db.get_session_state()` and injects result (including knowledge base content) into `BEGIN_SESSION` message. Agent starts with full context — no tool call needed.
- **Knowledge base**: `/workspace/analysis/knowledge_base.md` — single markdown file the agent reads/writes for persistent memory (watchlist, verified findings, rejected ideas, patterns). Displayed in sidebar KBPanel.
- **Analyst-only**: Agent recommends trades via `recommend_trade` DB tool. Exchange client methods remain for TUI executor.
- **Canonical views**: 3 DuckDB views (`v_latest_markets`, `v_daily_with_meta`, `v_active_recommendations`) replace `markets.jsonl` and provide SQL-native discovery. Created on startup after migrations.
- **DuckDB upserts**: Use raw SQL `text()` with `ON CONFLICT` clauses. `UniqueConstraint` on `kalshi_daily` and PKs on `events`/`kalshi_market_meta` serve as conflict targets.

### Logging

Centralized via `logging_config.py`. Call `setup_logging()` once per entry point; all other modules use `logger = logging.getLogger(__name__)` at module level.

**Where logs go:**
- **TUI app** (`make up`): per-session log files in `FA_LOG_DIR` (Docker sets `/app/state/logs/`). Each session creates `agent_{session_id}.log`, persisted on host at `./workspace/data/logs/`. `make logs` tails the most recent session log.
- **Collector** (`make collect`): stderr only (runs locally, not in Docker). Output visible in terminal, not saved to file.
- **Log levels**: INFO for normal operations, DEBUG for verbose (exception tracebacks in dashboard/portfolio refresh), WARNING for interrupts, ERROR for execution failures.
- **TUI display vs logging**: RichLog widgets show user-facing agent conversation. Python logging is a separate developer/ops channel — they don't overlap.

### Workspace scripts

`workspace/scripts/` contains analysis tools the agent runs inside the Docker container:
- `db_utils.py` — Shared DuckDB query helpers: `query(sql, params, limit=10000)`. Auto-applies LIMIT to prevent accidental full scans.
- `correlations.py` — Pairwise correlations within a category using DuckDB's `CORR()` aggregate
- `query_history.py` — kalshi_daily history queries via `v_daily_with_meta` view, with `ILIKE` search
- `market_info.py` — Full market lookup across all tables
- `category_overview.py` — Category summary via `v_latest_markets` view
- `query_recommendations.py` — Recommendation history queries with leg details
- `schema_reference.md` — Database schema reference: views, DuckDB features, guardrails, table definitions

## Code style

- **Ruff** for linting and formatting (line length 99, Python 3.12 target)
- **mypy** for type checking (lenient: `ignore_missing_imports`, no strict mode)
- `workspace/` is excluded from linting (agent-authored scripts, not package code)
- Pre-commit hooks run ruff lint + format on every commit
- **SQLAlchemy ORM preferred** — most database queries use ORM `select()`, `insert()`, `update()`, `delete()` on model classes. Upserts use raw SQL `text()` with `ON CONFLICT` for DuckDB compatibility. Add new query methods to `database.py` rather than writing inline SQL.

## Testing

- **pytest** + **pytest-asyncio** (asyncio_mode="auto"), **pytest-cov** for coverage
- `make test` runs all tests; `make test-cov` adds coverage report
- Tests live in `tests/` (core modules) and `tests/tui/` (TUI services, widgets, messages)
- Fixtures in `tests/conftest.py` (temp DuckDB, mock Kalshi client, sample data factories) and `tests/tui/conftest.py` (TUIServices wired to mocks)
- TUI widget tests use Textual's `App.run_test()` / `Pilot` for headless rendering

## Documentation

- **README.md** — project overview, architecture, quickstart, tool reference, database schema, config guide. Keep in sync with CLAUDE.md when making architectural changes (screen counts, tool counts, table counts, removed features, etc.).

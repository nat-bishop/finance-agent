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

This is a cross-platform arbitrage system for Kalshi and Polymarket US, built on `claude-agent-sdk`. The agent runs as an interactive REPL inside a Docker container with a sandboxed `/workspace` filesystem. It finds price discrepancies between platforms for identically-settling markets and produces structured arbitrage recommendations — it does not execute trades directly.

### Three-layer design

**Programmatic layer** (no LLM, runs separately):
- `collector.py` — snapshots market data from both Kalshi and Polymarket US to SQLite, generates `/workspace/data/markets.jsonl` (one JSON object per market for agent programmatic discovery)
- Run via: `make collect`

**Agent layer** (Claude REPL, runs on demand):
- Loads portfolios + pending recommendations from SQLite on startup, presents cross-platform dashboard
- Writes Python scripts against `markets.jsonl` for bulk cross-platform matching, then investigates top candidates with MCP tools
- Investigates opportunities: semantic market matching, price comparison, orderbook analysis
- Records trade recommendations via `recommend_trade` tool for separate review/execution
- All state persisted to SQLite for continuity across sessions

**TUI layer** (Textual, runs the app):
- `tui/app.py` — FinanceApp: initializes clients, DB, SDK, registers 4 screens (F1-F4)
- `tui/services.py` — async wrappers bridging sync exchange clients to Textual event loop
- `tui/screens/` — dashboard (chat+sidebar), recommendations, portfolio, history
- `tui/widgets/` — 7 widgets: agent_chat, rec_card, rec_list, portfolio_panel, status_bar, ask_modal, confirm_modal

### Source -> Runtime boundary

Source code (`src/finance_agent/`) is installed into the Docker image at `/app` and is **not visible to the agent at runtime**. The agent only sees `/workspace`, which contains reference scripts, analysis outputs, and data.

### Module roles

- **main.py** — Assembles `ClaudeAgentOptions`, builds SDK options. Entry point calls TUI. Wires `setup_logging()`.
- **logging_config.py** — `setup_logging()` configures root logger with stderr console + optional file handler. Idempotent, quiets noisy libraries (alembic, sqlalchemy, urllib3).
- **config.py** — Three config classes: `Credentials(BaseSettings)` loads API keys from `.env`/env vars; `TradingConfig` and `AgentConfig` are plain dataclasses (edit source to change defaults). Key trading defaults: `kalshi_max_position_usd=100`, `polymarket_max_position_usd=50`, `min_edge_pct=7.0`, `recommendation_ttl_minutes=60`. Also loads and templates `prompts/system.md`.
- **models.py** — SQLAlchemy ORM models (`DeclarativeBase`, `mapped_column`). Canonical schema definition for all 8 tables. Alembic autogenerate reads these.
- **tools.py** — Unified MCP tool factories via `@tool` decorator. `create_market_tools(kalshi, polymarket)` → 7 read-only tools, `create_db_tools(db, session_id)` → 1 tool (`recommend_trade` with legs array). Exchange is a parameter, not a namespace.
- **kalshi_client.py** — Thin wrapper around `kalshi_python_sync` SDK with rate limiting. Auth is RSA-PSS signing. Includes get_events (paginated).
- **polymarket_client.py** — Thin wrapper around `polymarket-us` SDK with rate limiting. Auth is Ed25519 signing. Includes get_trades (fixed), get_orders. Also exports `PM_INTENT_MAP`, `PM_INTENT_REVERSE`, `cents_to_usd` for frontend use.
- **hooks.py** — Hooks using `HookMatcher`. Auto-approve reads, recommendation counting via PostToolUse, session end with watchlist reminder.
- **database.py** — `AgentDatabase` class wrapping SQLite (WAL mode). Alembic migrations auto-run on startup. Events table has composite PK `(event_ticker, exchange)`. `get_session_state()` returns last_session, unreconciled_trades. Recommendation groups+legs CRUD for frontend.
- **collector.py** — Standalone data collector. Paginated event collection via `GET /events` (~3 API calls instead of ~500). Polymarket event collection. Generates `markets.jsonl` (one JSON object per market with denormalized event metadata). Also triggers incremental Kalshi daily history sync and upserts market metadata to `kalshi_market_meta`.
- **backfill.py** — Kalshi historical daily data sync from public S3 bucket. Dynamic: fetches only missing days (full backfill on empty DB, incremental on subsequent runs). Called by collector or standalone via `python -m finance_agent.backfill`.
- **rate_limiter.py** — Token-bucket rate limiter with separate read/write buckets.
- **api_base.py** — Base class for API clients with shared rate limiting and serialization.
- **prompts/system.md** — System prompt template with arb-only mission, settlement equivalence verification protocol, arbitrage structures, information hierarchy, market discovery workflow, recommendation protocol, risk rules.

### Key patterns

- **Factory + closure** for tools: `create_market_tools(kalshi, polymarket)` returns a list of `@tool`-decorated functions closed over both clients.
- **MCP tool naming**: `mcp__markets__{tool_name}`, `mcp__db__{tool_name}`. Two MCP servers, 8 tools total.
- **Unified conventions**: Exchange is a param, prices in cents, action+side for both platforms.
- **Config**: `Credentials` loads from env vars/`.env`; `TradingConfig` and `AgentConfig` are source-level defaults.
- **Hook ordering**: catch-all auto-approve → PostToolUse rec audit → Stop session end.
- **Startup context injection**: `main.py` calls `db.get_session_state()` and injects result into `BEGIN_SESSION` message. Agent starts with full context — no tool call needed.
- **Watchlist**: `/workspace/data/watchlist.md` — markdown file the agent reads/writes directly (replaces former DB watchlist tools).
- **Analyst-only**: Agent recommends trades via `recommend_trade` DB tool. Exchange client methods remain for future frontend executor.

### Logging

Centralized via `logging_config.py`. Call `setup_logging()` once per entry point; all other modules use `logger = logging.getLogger(__name__)` at module level.

**Where logs go:**
- **TUI app** (`make run` / `make dev`): stderr (visible in terminal) + `/workspace/data/agent.log` (persisted on host via Docker volume mount at `./workspace/data/agent.log`). View with `make logs`.
- **Collector** (`make collect`): stderr only (runs locally, not in Docker). Output visible in terminal, not saved to file.
- **Log levels**: INFO for normal operations, DEBUG for verbose (exception tracebacks in dashboard/portfolio refresh), WARNING for interrupts, ERROR for execution failures.
- **TUI display vs logging**: RichLog widgets show user-facing agent conversation. Python logging is a separate developer/ops channel — they don't overlap.

### Workspace reference scripts

`workspace/lib/` contains CLI tools for the agent's calculations:
- `normalize_prices.py` — Cross-platform price comparison with fee-adjusted edge (3 scenarios: leg-in maker/taker, both taker)
- `match_markets.py` — Bulk title similarity matching across platforms
- `kelly_size.py` — Kelly criterion position sizing (legacy reference, not used by agent)

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
- Fixtures in `tests/conftest.py` (temp DB, mock exchange clients, sample data factories) and `tests/tui/conftest.py` (TUIServices wired to mocks)
- TUI widget tests use Textual's `App.run_test()` / `Pilot` for headless rendering

## Documentation

- **README.md** — project overview, architecture, quickstart, tool reference, database schema, config guide. Keep in sync with CLAUDE.md when making architectural changes (screen counts, tool counts, table counts, removed features, etc.).

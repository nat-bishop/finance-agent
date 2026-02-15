# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Development
make build          # docker compose build
make run            # run agent REPL in Docker
make dev            # run with workspace volume mount (live edits)
make shell          # bash into container
make logs           # tail the agent log file (workspace/data/agent.log)

# Data pipeline
make collect        # snapshot market data to SQLite (both platforms)
make signals        # run quantitative scans on collected data
make scan           # collect + signals (full pipeline)
make backup         # backup SQLite database

# Testing
make test           # run all tests
make test-cov       # run tests with coverage report

# Code quality
uv run ruff check --fix src/       # auto-fix lint
uv run ruff format src/            # auto-format
uv run ruff check src/             # check lint (no auto-fix)
uv run ruff format --check src/    # check format (no auto-fix)
uv run mypy src/                   # type check
uv run pre-commit run --all-files  # run all hooks

# Dependencies
uv sync --extra dev # install with dev deps
uv lock             # regenerate lockfile

# Run locally (outside Docker)
uv run python -m finance_agent.main
```

## Architecture

This is a cross-platform arbitrage system for Kalshi and Polymarket US, built on `claude-agent-sdk`. The agent runs as an interactive REPL inside a Docker container with a sandboxed `/workspace` filesystem. It finds price discrepancies between platforms for identically-settling markets and produces structured arbitrage recommendations — it does not execute trades directly.

### Three-layer design

**Programmatic layer** (no LLM, runs separately):
- `collector.py` — snapshots market data from both Kalshi and Polymarket US to SQLite, generates `/workspace/data/active_markets.md` (category-grouped market listings for agent discovery)
- `signals.py` — runs 2 quantitative scans (arbitrage, cross-platform candidate) and writes signals to SQLite
- Run via: `make collect && make signals` (or `make scan`)

**Agent layer** (Claude REPL, runs on demand):
- Loads signals + portfolios + pending recommendations from SQLite on startup, presents cross-platform dashboard
- Reads `active_markets.md` to find cross-platform connections using semantic understanding
- Investigates opportunities: semantic market matching, price comparison, orderbook analysis
- Records trade recommendations via `recommend_trade` tool for separate review/execution
- All state persisted to SQLite for continuity across sessions

**TUI layer** (Textual, runs the app):
- `tui/app.py` — FinanceApp: initializes clients, DB, SDK, registers 5 screens (F1-F5)
- `tui/services.py` — async wrappers bridging sync exchange clients to Textual event loop
- `tui/screens/` — dashboard (chat+sidebar), recommendations, portfolio, signals, history
- `tui/widgets/` — 7 widgets: agent_chat, rec_card, rec_list, portfolio_panel, status_bar, ask_modal, confirm_modal

### Source -> Runtime boundary

Source code (`src/finance_agent/`) is installed into the Docker image at `/app` and is **not visible to the agent at runtime**. The agent only sees `/workspace`, which contains reference scripts, analysis outputs, and data.

### Module roles

- **main.py** — Assembles `ClaudeAgentOptions`, builds SDK options. Entry point calls TUI. Wires `setup_logging()`.
- **logging_config.py** — `setup_logging()` configures root logger with stderr console + optional file handler. Idempotent, quiets noisy libraries (alembic, sqlalchemy, urllib3).
- **config.py** — Three config classes: `Credentials(BaseSettings)` loads API keys from `.env`/env vars; `TradingConfig` and `AgentConfig` are plain dataclasses (edit source to change defaults). Key trading defaults: `kalshi_max_position_usd=100`, `polymarket_max_position_usd=50`, `min_edge_pct=7.0`, `recommendation_ttl_minutes=60`. Also loads and templates `prompts/system.md`.
- **models.py** — SQLAlchemy ORM models (`DeclarativeBase`, `mapped_column`). Canonical schema definition for all 9 tables. Alembic autogenerate reads these.
- **tools.py** — Unified MCP tool factories via `@tool` decorator. `create_market_tools(kalshi, polymarket)` → 8 read-only tools, `create_db_tools(db, session_id)` → 1 tool (`recommend_trade` with legs array). Exchange is a parameter, not a namespace.
- **kalshi_client.py** — Thin wrapper around `kalshi-python` SDK with rate limiting. Auth is RSA-PSS signing. Includes batch_create/cancel, amend_order, get_events (paginated).
- **polymarket_client.py** — Thin wrapper around `polymarket-us` SDK with rate limiting. Auth is Ed25519 signing. Includes get_trades (fixed), get_orders. Also exports `PM_INTENT_MAP`, `PM_INTENT_REVERSE`, `cents_to_usd` for frontend use.
- **hooks.py** — Hooks using `HookMatcher`. Auto-approve reads, recommendation counting via PostToolUse, session end with watchlist reminder.
- **database.py** — `AgentDatabase` class wrapping SQLite (WAL mode). Alembic migrations auto-run on startup. Events table has composite PK `(event_ticker, exchange)`. `get_session_state()` returns last_session, pending_signals, unreconciled_trades. Recommendation groups+legs CRUD for frontend.
- **collector.py** — Standalone data collector. Paginated event collection via `GET /events` (~3 API calls instead of ~500). Polymarket event collection. Generates enriched `active_markets.md` market listings (price, spread, volume, OI, DTE).
- **signals.py** — Standalone signal generator: 1 scan type (arbitrage). No LLM. Arbitrage detects bracket mispricing where mutually exclusive YES prices don't sum to ~100%.
- **rate_limiter.py** — Token-bucket rate limiter with separate read/write buckets.
- **api_base.py** — Base class for API clients with shared rate limiting and serialization.
- **prompts/system.md** — System prompt template with arb-only mission, settlement equivalence verification protocol, arbitrage structures, information hierarchy, market discovery workflow, recommendation protocol, risk rules.

### Key patterns

- **Factory + closure** for tools: `create_market_tools(kalshi, polymarket)` returns a list of `@tool`-decorated functions closed over both clients.
- **MCP tool naming**: `mcp__markets__{tool_name}`, `mcp__db__{tool_name}`. Two MCP servers, 9 tools total.
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
- **Collector / Signals** (`make collect` / `make signals`): stderr only (runs locally, not in Docker). Output visible in terminal, not saved to file.
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

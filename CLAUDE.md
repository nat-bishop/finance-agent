# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Development
make build          # docker compose build
make run            # run agent REPL in Docker
make dev            # run with workspace volume mount (live edits)
make shell          # bash into container

# Data pipeline
make collect        # snapshot market data to SQLite (both platforms)
make signals        # run quantitative scans on collected data
make scan           # collect + signals (full pipeline)
make backup         # backup SQLite database

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

This is a cross-platform prediction market arbitrage agent for Kalshi and Polymarket US, built on `claude-agent-sdk`. The agent runs as an interactive REPL inside a Docker container with a sandboxed `/workspace` filesystem.

### Two-layer design

**Programmatic layer** (no LLM, runs separately):
- `collector.py` — snapshots market data from both Kalshi and Polymarket US to SQLite
- `signals.py` — runs 7 quantitative scans (arbitrage, wide_spread, cross-platform mismatch, structural arb, theta_decay, momentum, calibration) and writes signals to SQLite
- Run via: `make collect && make signals` (or `make scan`)

**Agent layer** (Claude REPL, runs on demand):
- Loads signals + portfolios from SQLite on startup, presents cross-platform dashboard
- Investigates opportunities: semantic market matching, price comparison, orderbook analysis
- Recommends paired trades with full reasoning, awaits user approval
- All state persisted to SQLite for continuity across sessions

### Source -> Runtime boundary

Source code (`src/finance_agent/`) is installed into the Docker image at `/app` and is **not visible to the agent at runtime**. The agent only sees `/workspace`, which contains reference scripts, analysis outputs, and data.

### Module roles

- **main.py** — Assembles `ClaudeAgentOptions`, initializes DB, creates session, auto-resolves predictions, injects startup context into `BEGIN_SESSION`, runs the REPL loop.
- **config.py** — Pydantic settings with TOML profile support (`config.toml` has `[demo]`/`[prod]` sections). Env vars override TOML values. `kalshi_max_position_usd`, `polymarket_max_position_usd`, `polymarket_fee_rate = 0.0`. Also loads and templates `prompts/system.md`.
- **tools.py** — Unified MCP tool factories via `@tool` decorator. `create_market_tools(kalshi, polymarket, config)` → 11 tools, `create_db_tools(db)` → 1 tool (`log_prediction`). Exchange is a parameter, not a namespace.
- **kalshi_client.py** — Thin wrapper around `kalshi-python` SDK with rate limiting. Auth is RSA-PSS signing. Includes batch_create/cancel, amend_order, get_events (paginated).
- **polymarket_client.py** — Thin wrapper around `polymarket-us` SDK with rate limiting. Auth is Ed25519 signing. Includes get_trades (fixed), get_orders.
- **hooks.py** — Hooks using `HookMatcher`. Catch-all auto-approve for reads, trade/amend/cancel validation with position-limit checks (`deny` if exceeded, `ask` if within limits), PostToolUse audit to SQLite `trades` table, session end with watchlist reminder. `_can_use_tool` in main.py handles `AskUserQuestion` and provides trade approval safety net.
- **database.py** — `AgentDatabase` class wrapping SQLite (WAL mode). Alembic migrations auto-run on startup. Events table has composite PK `(event_ticker, exchange)`. `auto_resolve_predictions()` matches against settled market_snapshots. `_compute_calibration()` for Brier score. `get_session_state()` includes calibration, signal_history, unreconciled trades.
- **collector.py** — Standalone data collector. Paginated event collection via `GET /events` (~3 API calls instead of ~500). Polymarket event collection.
- **signals.py** — Standalone signal generator: 7 scan types (arbitrage, wide_spread, cross_platform_mismatch, structural_arb, theta_decay, momentum, calibration). No LLM.
- **rate_limiter.py** — Token-bucket rate limiter with separate read/write buckets.
- **api_base.py** — Base class for API clients with shared rate limiting and serialization.
- **prompts/system.md** — System prompt template with unified tool docs, per-signal investigation protocols, order management, signal priority framework.

### Key patterns

- **Factory + closure** for tools: `create_market_tools(kalshi, polymarket, config)` returns a list of `@tool`-decorated functions closed over both clients.
- **MCP tool naming**: `mcp__markets__{tool_name}`, `mcp__db__{tool_name}`. Two MCP servers, 12 tools total.
- **Unified conventions**: Exchange is a param, prices in cents, action+side for both platforms. Tool layer handles Polymarket USD/intent conversion.
- **Config priority**: env vars > TOML profile > Pydantic defaults. Profile selected by `AGENT_PROFILE` env var.
- **Hook ordering**: trade/amend/cancel matchers (ask/deny) → catch-all auto-approve → PostToolUse audit → Stop session end.
- **Startup context injection**: `main.py` calls `db.get_session_state()` and injects result into `BEGIN_SESSION` message. Agent starts with full context — no tool call needed.
- **Watchlist**: `/workspace/data/watchlist.md` — markdown file the agent reads/writes directly (replaces former DB watchlist tools).

### Workspace reference scripts

`workspace/lib/` contains CLI tools for the agent's calculations:
- `normalize_prices.py` — Cross-platform price comparison with fee-adjusted edge
- `kelly_size.py` — Kelly criterion position sizing
- `match_markets.py` — Bulk title similarity matching across platforms

## Code style

- **Ruff** for linting and formatting (line length 99, Python 3.12 target)
- **mypy** for type checking (lenient: `ignore_missing_imports`, no strict mode)
- `workspace/` is excluded from linting (agent-authored scripts, not package code)
- Pre-commit hooks run ruff lint + format on every commit

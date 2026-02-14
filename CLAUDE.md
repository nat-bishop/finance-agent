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
make format         # auto-fix lint + format (ruff)
make lint           # check lint + format + mypy (no auto-fix)
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
- `signals.py` — runs quantitative scans (arbitrage, spread, cross-platform mismatch, structural arb) and writes signals to SQLite
- Run via: `make collect && make signals` (or `make scan`)

**Agent layer** (Claude REPL, runs on demand):
- Loads signals + portfolios from SQLite on startup, presents cross-platform dashboard
- Investigates opportunities: semantic market matching, price comparison, orderbook analysis
- Recommends paired trades with full reasoning, awaits user approval
- All state persisted to SQLite for continuity across sessions

### Source -> Runtime boundary

Source code (`src/finance_agent/`) is installed into the Docker image at `/app` and is **not visible to the agent at runtime**. The agent only sees `/workspace`, which contains reference scripts, analysis outputs, and data.

### Module roles

- **main.py** — Assembles `ClaudeAgentOptions`, initializes DB, creates session, sends `BEGIN_SESSION` to trigger startup protocol, runs the REPL loop. Conditionally creates Polymarket MCP server.
- **config.py** — Pydantic settings with TOML profile support (`config.toml` has `[demo]`/`[prod]` sections). Env vars override TOML values. Includes Polymarket config fields. Also loads and templates `prompts/system.md`.
- **tools.py** — Factory that creates MCP tool definitions via `@tool` decorator. `create_kalshi_tools()`, `create_polymarket_tools()`, and `create_db_tools()`.
- **kalshi_client.py** — Thin wrapper around `kalshi-python` SDK with rate limiting. Auth is RSA-PSS signing.
- **polymarket_client.py** — Thin wrapper around `polymarket-us` SDK with rate limiting. Auth is Ed25519 signing.
- **permissions.py** — `can_use_tool` callback. Auto-approves reads and DB tools; validates trading limits on both platforms' `place_order`; shows formatted trade approval prompt.
- **hooks.py** — Hooks using `HookMatcher`. Auto-approve reads (both platforms), trade validation with `permissionDecision: ask/deny`, PostToolUse audit to SQLite `trades` table, session end.
- **database.py** — `AgentDatabase` class wrapping SQLite (WAL mode). Schema includes `exchange` column on market_snapshots, signals, trades, watchlist.
- **collector.py** — Standalone data collector for both Kalshi and Polymarket. No LLM.
- **signals.py** — Standalone signal generator: arbitrage, spread, cross-platform mismatch, structural arb. No LLM.
- **rate_limiter.py** — Token-bucket rate limiter with separate read/write buckets.
- **prompts/system.md** — System prompt template with `{{VARIABLE}}` placeholders substituted from config.

### Key patterns

- **Factory + closure** for tools and permissions: `create_kalshi_tools(client, config)` returns a list of `@tool`-decorated functions closed over the client.
- **MCP tool naming**: `mcp__kalshi__{tool_name}`, `mcp__polymarket__{tool_name}`, `mcp__db__{tool_name}`.
- **Config priority**: env vars > TOML profile > Pydantic defaults. Profile selected by `AGENT_PROFILE` env var.
- **Hook ordering**: auto-approve reads → trade validation → audit → session end.

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

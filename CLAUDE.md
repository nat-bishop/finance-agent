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
make collect        # snapshot market data to SQLite
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

This is an AI trading agent for Kalshi prediction markets, built on `claude-agent-sdk`. The agent runs as an interactive REPL inside a Docker container with a sandboxed `/workspace` filesystem.

### Two-layer design

**Programmatic layer** (no LLM, runs separately):
- `collector.py` — snapshots market data to SQLite via paginated API calls
- `signals.py` — runs quantitative scans (arbitrage, spread, mean reversion, theta decay, calibration, time-series) and writes signals to SQLite
- Run via: `make collect && make signals` (or `make scan`)

**Agent layer** (Claude REPL, runs on demand):
- Loads signals + portfolio from SQLite on startup, presents dashboard
- Investigates opportunities dynamically using Kalshi API + skill scripts
- Recommends trades with full reasoning, awaits user approval
- All state persisted to SQLite for continuity across sessions

### Source → Runtime boundary

Source code (`src/finance_agent/`) is installed into the Docker image at `/app` and is **not visible to the agent at runtime**. The agent only sees `/workspace`, which contains skills, analysis scripts, and data.

### Module roles

- **main.py** — Assembles `ClaudeAgentOptions`, initializes DB, creates session, sends `BEGIN_SESSION` to trigger startup protocol, runs the REPL loop.
- **config.py** — Pydantic settings with TOML profile support (`config.toml` has `[demo]`/`[prod]` sections). Env vars override TOML values. Also loads and templates `prompts/system.md`.
- **tools.py** — Factory that creates MCP tool definitions via `@tool` decorator. `create_kalshi_tools()` for API access, `create_db_tools()` for database access.
- **kalshi_client.py** — Thin wrapper around `kalshi-python` SDK with rate limiting. Auth is RSA-PSS signing with API key ID + PEM private key.
- **permissions.py** — `can_use_tool` callback. Auto-approves reads and DB tools; validates trading limits on `place_order`; shows formatted trade approval prompt; handles `AskUserQuestion` with terminal I/O.
- **hooks.py** — Hooks using `HookMatcher`. Stream keepalive (required for SDK), auto-approve reads, trade validation with `permissionDecision: ask/deny`, PostToolUse audit to SQLite `trades` table, session end to SQLite.
- **database.py** — `AgentDatabase` class wrapping SQLite (WAL mode). Schema: market_snapshots, events, signals, trades, predictions, portfolio_snapshots, sessions, watchlist.
- **collector.py** — Standalone data collector script. No LLM.
- **signals.py** — Standalone signal generator script. No LLM.
- **rate_limiter.py** — Token-bucket rate limiter with separate read/write buckets.
- **prompts/system.md** — System prompt template with `{{VARIABLE}}` placeholders substituted from `TradingConfig`.

### Key patterns

- **Factory + closure** for tools and permissions: `create_kalshi_tools(client, config)` returns a list of `@tool`-decorated functions closed over the client.
- **MCP tool naming**: `mcp__kalshi__{tool_name}`, `mcp__db__{tool_name}`.
- **Config priority**: env vars > TOML profile > Pydantic defaults. Profile selected by `AGENT_PROFILE` env var.
- **Hook ordering**: keepalive → auto-approve reads → trade validation → audit → session end.
- **PreToolUse must return `{"continue_": True}`** from at least one hook for `can_use_tool` to work (SDK requirement).

### Workspace skills

`workspace/.claude/skills/` contains 6 active quantitative finance skills (kelly-sizing, monte-carlo, bayesian-updating, binary-option-pricing, risk-managing, market-microstructure). Each has a `SKILL.md` (methodology) and `scripts/` (executable Python). These are read-only reference material for the agent.

5 additional skills are archived in `workspace/.claude/skills/_archived/` (absorbed into the signal generator or not needed).

## Code style

- **Ruff** for linting and formatting (line length 99, Python 3.12 target)
- **mypy** for type checking (lenient: `ignore_missing_imports`, no strict mode)
- `workspace/` is excluded from linting (agent-authored scripts, not package code)
- Pre-commit hooks run ruff lint + format on every commit

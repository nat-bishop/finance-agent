# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Development
make build          # docker compose build
make run            # run agent REPL in Docker
make dev            # run with workspace volume mount (live edits)
make shell          # bash into container

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

### Source → Runtime boundary

Source code (`src/finance_agent/`) is installed into the Docker image at `/app` and is **not visible to the agent at runtime**. The agent only sees `/workspace`, which contains skills, analysis scripts, data, and the trade journal.

### Module roles

- **main.py** — Assembles `ClaudeAgentOptions` and runs the REPL loop. Wires together all other modules.
- **config.py** — Pydantic settings with TOML profile support (`config.toml` has `[demo]`/`[prod]` sections). Env vars override TOML values. Also loads and templates `prompts/system.md`.
- **tools.py** — Factory that creates MCP tool definitions via `@tool` decorator, using closures over a `KalshiAPIClient` instance and `TradingConfig`.
- **kalshi_client.py** — Thin wrapper around `kalshi-python` SDK. Auth is RSA-PSS signing with API key ID + PEM private key.
- **permissions.py** — `can_use_tool` callback. Always allows reads; validates order count/position size on `place_order`; gates filesystem writes to `analysis/`, `data/`, `lib/`.
- **hooks.py** — Audit hooks using `HookMatcher`. Logs `PreToolUse`/`PostToolUse` for orders and `Stop` for session summaries to `trade_journal/trades.jsonl` (JSONL, append-only).
- **prompts/system.md** — System prompt template with `{{VARIABLE}}` placeholders substituted from `TradingConfig`.

### Key patterns

- **Factory + closure** for tools and permissions: `create_kalshi_tools(client, config)` returns a list of `@tool`-decorated functions closed over the client.
- **MCP tool naming**: `mcp__kalshi__{tool_name}` (e.g., `mcp__kalshi__place_order`).
- **Config priority**: env vars > TOML profile > Pydantic defaults. Profile selected by `AGENT_PROFILE` env var.

### Workspace skills

`workspace/.claude/skills/` contains 11 quantitative finance skills (kelly-sizing, monte-carlo, bayesian-updating, etc.). Each has a `SKILL.md` (methodology) and `scripts/` (executable Python). These are read-only reference material for the agent — it reads the methodology and runs the scripts to produce analysis.

## Code style

- **Ruff** for linting and formatting (line length 99, Python 3.12 target)
- **mypy** for type checking (lenient: `ignore_missing_imports`, no strict mode)
- `workspace/` is excluded from linting (agent-authored scripts, not package code)
- Pre-commit hooks run ruff lint + format on every commit

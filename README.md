# Finance Agent

AI-powered trading agent for [Kalshi](https://kalshi.com) prediction markets, built on the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-agent-sdk).

The agent investigates market opportunities, applies quantitative analysis via built-in skill scripts, and recommends trades with full reasoning — waiting for your approval before executing.

## How it works

**Two-layer architecture:**

1. **Data pipeline** (programmatic, no LLM) — collects market snapshots and runs quantitative scans to surface signals: arbitrage, wide spreads, mean reversion, theta decay, calibration bias, and trend divergence.

2. **Agent** (Claude REPL) — loads pre-computed signals on startup, presents a dashboard, then investigates opportunities interactively. Uses Kelly sizing, Bayesian updating, binary option pricing, risk analysis, Monte Carlo simulation, and microstructure analysis as callable skill scripts.

All state lives in SQLite for continuity across sessions — trade history, probability predictions, portfolio snapshots, watchlists, and signals.

## Quickstart

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (for sandboxed execution)
- Kalshi API credentials (key ID + RSA private key)
- Anthropic API key

### Setup

```bash
# Clone and install
git clone <repo-url> && cd finance-agent
uv sync --extra dev --extra skills

# Configure credentials
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY, KALSHI_API_KEY_ID, and key path
```

### Run with Docker (recommended)

```bash
make build                # build the container
make scan                 # collect market data + generate signals
make run                  # start the agent REPL
```

### Run locally

```bash
make scan                 # collect data + signals
uv run python -m finance_agent.main
```

## Usage

On startup the agent automatically:
1. Loads session state from the database (last session summary, pending signals, watchlist)
2. Fetches your current portfolio from Kalshi
3. Resolves any predictions that settled since last session
4. Presents a dashboard and waits for your direction

```
Kalshi Trading Agent
Profile: demo  |  Model: claude-sonnet-4-5-20250929
Environment: demo
Max position: $50.0
Max portfolio: $500.0
Session: a3f1b2c8

> investigate the top signal
> look at the Fed rate markets
> what's on my watchlist?
```

Trades require explicit approval — the agent presents a formatted summary and waits for `y/n`.

## Data pipeline

```bash
make collect    # snapshot all open/settled markets + event structure to SQLite
make signals    # run 6 quantitative scans on collected data
make scan       # both in sequence
make backup     # backup the database
```

The collector and signal generator are standalone Python scripts with no LLM dependency. Run them on a schedule (e.g. hourly cron) to keep signals fresh.

## Configuration

Trading parameters are set in `config.toml` with `[demo]` and `[prod]` profiles:

| Parameter | Demo | Prod |
|---|---|---|
| Max position | $50 | $100 |
| Max portfolio | $500 | $1,000 |
| Max contracts/order | 100 | 50 |
| Min edge required | 5% | 7% |
| Claude budget/session | $1 | $2 |

Select a profile via the `AGENT_PROFILE` env var. Environment variables override TOML values.

## Project structure

```
src/finance_agent/
  main.py             # REPL entry point, session lifecycle
  config.py           # Pydantic settings, TOML profile loading
  database.py         # SQLite (WAL mode), schema, queries
  tools.py            # MCP tool factories (Kalshi API + DB)
  kalshi_client.py    # Kalshi SDK wrapper with rate limiting
  permissions.py      # Permission handler, trade approval, AskUserQuestion
  hooks.py            # Audit hooks, auto-approve, trade validation
  collector.py        # Market data collector (standalone)
  signals.py          # Signal generator (standalone)
  rate_limiter.py     # Token-bucket rate limiter
  prompts/system.md   # System prompt template

workspace/
  .claude/skills/     # 6 quantitative finance skills (read-only)
  analysis/           # Agent-written analysis scripts
  data/               # SQLite database, session logs
  lib/                # Reusable utilities
```

## Development

```bash
make format             # auto-fix lint + format
make lint               # check lint + format + mypy
uv run pre-commit run --all-files
```

Ruff for linting/formatting, mypy for type checking. Pre-commit hooks enforce both on every commit.

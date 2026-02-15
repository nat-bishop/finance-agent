# Finance Agent

Cross-platform prediction market arbitrage agent for [Kalshi](https://kalshi.com) and [Polymarket US](https://polymarket.us), built on the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-agent-sdk).

Finds price discrepancies between platforms, verifies market equivalence, and recommends paired trades with full reasoning — waiting for your approval before executing.

## Architecture

**Two-layer design:**

1. **Programmatic layer** (no LLM) — `collector.py` snapshots market data from both platforms, `signals.py` runs 7 quantitative scans to surface opportunities: arbitrage, wide spreads, cross-platform mismatch, structural arb, theta decay, momentum, and calibration.

2. **Agent layer** (Claude REPL) — loads pre-computed signals and session state on startup, presents a cross-platform dashboard, investigates opportunities using unified market tools, and recommends paired trades. All state persists in SQLite for continuity across sessions.

## Quickstart

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (for sandboxed execution)
- Kalshi API credentials (key ID + RSA private key)
- Anthropic API key
- Optional: Polymarket US credentials (key ID + secret key)

### Setup

```bash
git clone <repo-url> && cd finance-agent
uv sync --extra dev --extra skills

cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, KALSHI_API_KEY_ID, key path
# Optional: POLYMARKET_KEY_ID, POLYMARKET_SECRET_KEY
```

### Run

```bash
make build    # build Docker container
make scan     # collect market data + generate signals
make run      # start the agent REPL
```

Or locally: `make scan && uv run python -m finance_agent.main`

## Data Pipeline

```bash
make collect    # snapshot markets + events from both platforms to SQLite
make signals    # run 7 quantitative scans on collected data
make scan       # both in sequence
make backup     # backup the database
```

The collector and signal generator are standalone scripts with no LLM dependency. Run them on a schedule (e.g. hourly cron) to keep signals fresh.

### Signal Types

| Signal | Description |
|--------|-------------|
| `arbitrage` | Bracket YES prices not summing to ~100% (single-platform) |
| `wide_spread` | Wide bid-ask with volume — limit order at mid captures half-spread |
| `cross_platform_mismatch` | Same market, different prices on Kalshi vs Polymarket |
| `structural_arb` | Kalshi bracket events vs Polymarket individual markets |
| `theta_decay` | Near-expiry (<3 days) markets with uncertain prices (20-80c) |
| `momentum` | Consistent directional movement (3+ snapshots, >5c move) |
| `calibration` | Meta-signal from prediction accuracy (Brier score, 10+ resolved) |

## Agent Tools

12 unified MCP tools across 2 servers (`mcp__markets__*` and `mcp__db__*`):

### Market Tools (11)

| Tool | Params | Notes |
|------|--------|-------|
| `search_markets` | `exchange?`, `query?`, `status?`, `event_id?`, `limit?` | Omit exchange = both platforms |
| `get_market` | `exchange`, `market_id` | Full details, rules, settlement source |
| `get_orderbook` | `exchange`, `market_id`, `depth?` | `depth=1` uses Polymarket BBO |
| `get_event` | `exchange`, `event_id` | Event with nested markets |
| `get_price_history` | `market_id`, `start_ts?`, `end_ts?`, `interval?` | Kalshi only |
| `get_trades` | `exchange`, `market_id`, `limit?` | Recent executions |
| `get_portfolio` | `exchange?`, `include_fills?`, `include_settlements?` | Omit exchange = both |
| `get_orders` | `exchange?`, `market_id?`, `status?` | Omit exchange = all platforms |
| `place_order` | `exchange`, `orders[]` | Batch on Kalshi (up to 20), single on Polymarket |
| `amend_order` | `order_id`, `price_cents?`, `quantity?` | Kalshi only, preserves FIFO |
| `cancel_order` | `exchange`, `order_ids[]` | Batch cancel supported |

### Database Tools (1)

| Tool | Notes |
|------|-------|
| `log_prediction` | Record probability prediction for calibration (market_ticker, prediction, context) |

**Conventions:** All prices in cents (1-99). Actions: `buy`/`sell`. Sides: `yes`/`no`. Exchange: `kalshi` or `polymarket`. The tool layer handles all conversion (Polymarket USD decimals, intents).

## Trading Flow

```
Signal → Investigation → Verification → Sizing → Approval → Execution → Audit
```

1. **Signal** — Pre-computed by `signals.py`, loaded at startup
2. **Investigation** — Agent follows per-signal protocol (cross-platform mismatch, arbitrage, etc.)
3. **Verification** — Settlement equivalence, executable orderbook prices
4. **Sizing** — `normalize_prices.py` for fee-adjusted edge, `kelly_size.py` for position size
5. **Approval** — Agent presents trade, user approves via hook prompt
6. **Execution** — Unified `place_order` routes to correct exchange
7. **Audit** — PostToolUse hook logs to `trades` table in SQLite

## Configuration

`config.toml` with `[demo]` and `[prod]` profiles. Select via `AGENT_PROFILE` env var.

| Parameter | Demo | Prod |
|---|---|---|
| Kalshi max position | $50 | $100 |
| Polymarket max position | $50 | $50 |
| Max portfolio | $500 | $1,000 |
| Max contracts/order | 100 | 50 |
| Min edge required | 5% | 7% |
| Kalshi fee rate | 3% | 3% |
| Polymarket fee rate | 0% | 0% |
| Claude budget/session | $1 | $2 |

Environment variables override TOML values.

## Database Schema

SQLite (WAL mode) at `/workspace/data/agent.db`. Schema managed by Alembic (auto-migrated on startup). 8 tables:

| Table | Written by | Read by | Key columns |
|-------|-----------|---------|-------------|
| `market_snapshots` | collector | signals, agent | exchange, ticker, mid_price_cents, status |
| `events` | collector | signals, agent | (event_ticker, exchange) PK, markets_json |
| `signals` | signals | agent | scan_type, exchange, signal_strength, status |
| `trades` | hooks | agent | exchange, ticker, action, side, price_cents |
| `predictions` | agent | signals, startup | prediction, outcome, market_ticker |
| `portfolio_snapshots` | startup | agent | balance_usd, positions_json |
| `sessions` | main | agent | started_at, summary, trades_placed |
| `watchlist` | legacy | — | (ticker, exchange) PK — migrated to `/workspace/data/watchlist.md` |

## Workspace

```
/workspace/
  lib/
    normalize_prices.py   # Cross-platform price comparison with fee-adjusted edge
    kelly_size.py         # Kelly criterion position sizing
    match_markets.py      # Bulk title similarity matching across platforms
  analysis/               # Agent-written analysis (writable)
  data/
    agent.db              # SQLite database
    watchlist.md          # Markets to monitor across sessions
    session.log           # Session scratch notes
  backups/                # DB backups (auto, max 7)
```

## Project Structure

```
src/finance_agent/
  main.py              # REPL entry point, session lifecycle, startup context injection
  config.py            # Pydantic settings, TOML profile loading
  database.py          # SQLite (WAL mode), Alembic migrations, auto-resolve predictions
  tools.py             # Unified MCP tool factories (market + DB)
  kalshi_client.py     # Kalshi SDK wrapper (batch, amend, paginated events)
  polymarket_client.py # Polymarket US SDK wrapper
  hooks.py             # Audit hooks, trade validation, session lifecycle
  collector.py         # Market data collector (both platforms, paginated events)
  signals.py           # Signal generator (7 scan types)
  rate_limiter.py      # Token-bucket rate limiter
  api_base.py          # Shared base class for API clients
  migrations/          # Alembic schema migrations
  prompts/system.md    # System prompt template
```

## Development

```bash
make format             # auto-fix lint + format (ruff)
make lint               # check lint + format + mypy
make dev                # run with live workspace volume mount
make shell              # bash into container
uv run pre-commit run --all-files
```

Ruff for linting/formatting (line length 99, Python 3.12 target), mypy for type checking. Pre-commit hooks enforce both.

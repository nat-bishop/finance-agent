# Finance Agent

Cross-platform prediction market analyst for [Kalshi](https://kalshi.com) and [Polymarket US](https://polymarket.us), built on the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-agent-sdk).

Finds price discrepancies between platforms, verifies market equivalence, and produces structured trade recommendations. Includes a terminal UI for reviewing recommendations, executing trades, and monitoring positions.

## Architecture

**Three-layer design:**

1. **Programmatic layer** (no LLM) — `collector.py` snapshots market data from both platforms and generates `active_markets.md` (category-grouped listings), `signals.py` runs 5 quantitative scans to surface opportunities: arbitrage, wide spreads, theta decay, momentum, and calibration.

2. **Agent layer** (Claude) — reads `active_markets.md` to find cross-platform connections using semantic understanding, investigates opportunities using unified market tools, and records trade recommendations via `recommend_trade`. All state persists in SQLite for continuity across sessions.

3. **TUI layer** ([Textual](https://textual.textualize.io/)) — terminal interface embedding the agent chat alongside portfolio monitoring, recommendation review, and order execution. Replaces the raw REPL with 5 navigable screens.

### TUI Screens

| Key | Screen | Purpose |
|-----|--------|---------|
| F1 | Dashboard | Agent chat (left) + portfolio summary & pending recs sidebar (right) |
| F2 | Recommendations | Full recommendation review with grouped execution and rejection |
| F3 | Portfolio | Balances, positions, resting orders, recent trades across both exchanges |
| F4 | Signals | Pending signals, calibration summary (Brier score), signal history |
| F5 | History | Session list with drill-down to per-session trades and recommendations |

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
make run      # start the TUI
```

Or locally: `make scan && uv run python -m finance_agent.main`

## Data Pipeline

```bash
make collect    # snapshot markets + events from both platforms to SQLite, generate active_markets.md
make signals    # run 5 quantitative scans on collected data
make scan       # both in sequence
make backup     # backup the database
```

The collector and signal generator are standalone scripts with no LLM dependency. Run them on a schedule (e.g. hourly cron) to keep signals fresh.

### Signal Types

| Signal | Description |
|--------|-------------|
| `arbitrage` | Bracket YES prices not summing to ~100% (single-platform) |
| `wide_spread` | Wide bid-ask with volume — limit order at mid captures half-spread |
| `theta_decay` | Near-expiry (<3 days) markets with uncertain prices (20-80c) |
| `momentum` | Consistent directional movement (3+ snapshots, >5c move) |
| `calibration` | Meta-signal from prediction accuracy (Brier score, 10+ resolved) |

Cross-platform matching (formerly `cross_platform_mismatch` and `structural_arb`) is now handled by the agent via semantic analysis of `active_markets.md`.

## Agent Tools

10 unified MCP tools across 2 servers (`mcp__markets__*` and `mcp__db__*`):

### Market Tools (8)

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

### Database Tools (2)

| Tool | Notes |
|------|-------|
| `log_prediction` | Record probability prediction for calibration (market_ticker, prediction, context) |
| `recommend_trade` | Record trade recommendation with thesis, edge, confidence. Use `group_id` for paired arb legs. |

**Conventions:** All prices in cents (1-99). Actions: `buy`/`sell`. Sides: `yes`/`no`. Exchange: `kalshi` or `polymarket`.

## Recommendation Lifecycle

```
Agent recommends → TUI review → Execute or Reject
```

1. **Agent calls `recommend_trade`** — creates a pending recommendation in SQLite with thesis, edge estimate, confidence, and optional `group_id` for paired arb legs. Recommendations expire after `recommendation_ttl_minutes` (default 60).

2. **TUI displays pending recs** — sidebar on the dashboard (F1) and full review on the recommendations screen (F2). Grouped by `group_id` for multi-leg arbs. Shows edge, confidence, expiry countdown.

3. **Execute** — confirmation modal shows order details and cost. On confirm, the TUI service layer validates position limits, places orders via the exchange clients, logs trades for audit, and updates recommendation status.

4. **Reject** — marks the recommendation as rejected. Visible in history.

## Analysis Flow

```
Discovery → Investigation → Verification → Sizing → Recommendation
```

1. **Discovery** — Agent reads `active_markets.md`, finds cross-platform connections by category; also reviews pre-computed arithmetic signals
2. **Investigation** — Agent follows per-signal protocol (semantic matching, arbitrage, etc.)
3. **Verification** — Settlement equivalence, executable orderbook prices
4. **Sizing** — `normalize_prices.py` for fee-adjusted edge, `kelly_size.py` for position size
5. **Recommendation** — Agent calls `recommend_trade` for each leg, stored in DB for review

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
| Recommendation TTL | 60 min | 60 min |

Environment variables override TOML values.

## Database Schema

SQLite (WAL mode) at `/workspace/data/agent.db`. Schema managed by Alembic (auto-migrated on startup). 9 tables:

| Table | Written by | Read by | Key columns |
|-------|-----------|---------|-------------|
| `market_snapshots` | collector | signals, agent | exchange, ticker, mid_price_cents, status |
| `events` | collector | signals, agent | (event_ticker, exchange) PK, markets_json |
| `signals` | signals | agent, TUI | scan_type, exchange, signal_strength, status |
| `trades` | TUI executor | agent, TUI | exchange, ticker, action, side, price_cents |
| `recommendations` | agent | TUI | exchange, market_id, action, side, status, group_id |
| `predictions` | agent | signals, startup | prediction, outcome, market_ticker |
| `portfolio_snapshots` | TUI | TUI | balance_usd, positions_json |
| `sessions` | main | agent, TUI | started_at, summary, trades_placed, recommendations_made |
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
    active_markets.md     # Category-grouped market listings (generated by collector)
    watchlist.md          # Markets to monitor across sessions
    session.log           # Session scratch notes
  backups/                # DB backups (auto, max 7)
```

## Project Structure

```
src/finance_agent/
  main.py              # Entry point, SDK options, launches TUI
  config.py            # Pydantic settings, TOML profile loading
  database.py          # SQLite (WAL mode), Alembic migrations, recommendation + trade CRUD
  tools.py             # Unified MCP tool factories (8 market + 2 DB)
  kalshi_client.py     # Kalshi SDK wrapper (batch, amend, paginated events)
  polymarket_client.py # Polymarket US SDK wrapper, intent maps
  hooks.py             # Recommendation counting, session lifecycle
  collector.py         # Market data collector (both platforms, market listings)
  signals.py           # Signal generator (5 scan types)
  rate_limiter.py      # Token-bucket rate limiter
  api_base.py          # Shared base class for API clients
  migrations/          # Alembic schema migrations
  prompts/system.md    # System prompt template
  tui/                 # Textual TUI frontend
    app.py             # FinanceApp: init, screen registration, keybindings
    services.py        # Async service layer (DB queries, order execution)
    messages.py        # Inter-widget message types
    agent.tcss         # CSS stylesheet
    screens/
      dashboard.py     # F1: agent chat + sidebar (portfolio + pending recs)
      recommendations.py # F2: full recommendation review + execution
      portfolio.py     # F3: balances, positions, orders
      signals.py       # F4: signal table + calibration
      history.py       # F5: session history with drill-down
    widgets/
      agent_chat.py    # RichLog + Input with async streaming
      rec_card.py      # Single recommendation card
      rec_list.py      # Grouped recommendation list
      portfolio_panel.py # Compact balance summary
      status_bar.py    # Session info bar
      ask_modal.py     # Agent question dialog
      confirm_modal.py # Order confirmation dialog
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

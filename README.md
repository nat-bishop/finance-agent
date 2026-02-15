# Finance Agent

Cross-platform arbitrage system for [Kalshi](https://kalshi.com) and [Polymarket US](https://polymarket.us), built on the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-agent-sdk).

Finds markets that resolve to the same outcome across platforms, verifies identical settlement criteria, and produces structured arbitrage recommendations. Includes a terminal UI for reviewing recommendations, executing trades, and monitoring positions.

## Architecture

**Three-layer design:**

1. **Programmatic layer** (no LLM) — `collector.py` snapshots market data from both platforms, generates enriched `active_markets.md` (grouped by category → exchange → event, with price sums for bracket arb visibility), and runs signal generation. `signals.py` scans for bracket arbitrage with liquidity-weighted scoring.

2. **Agent layer** (Claude) — reads `active_markets.md` to find cross-platform connections using semantic understanding, investigates opportunities using unified market tools, and records trade recommendations via `recommend_trade` with a `legs` array. All state persists in SQLite for continuity across sessions.

3. **TUI layer** ([Textual](https://textual.textualize.io/)) — terminal interface embedding the agent chat alongside portfolio monitoring, recommendation review, and order execution. 5 navigable screens.

### TUI Screens

| Key | Screen | Purpose |
|-----|--------|---------|
| F1 | Dashboard | Agent chat (left) + portfolio summary & pending recs sidebar (right) |
| F2 | Recommendations | Full recommendation review with grouped execution and rejection |
| F3 | Portfolio | Balances, positions, resting orders, recent trades across both exchanges |
| F4 | Signals | Pending signal table |
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
make collect    # snapshot markets + events to SQLite, generate active_markets.md, run signals
make signals    # run signal scans standalone (also runs automatically at end of collect)
make scan       # collect + signals (legacy alias, collect already runs signals)
make backup     # backup the database
make startup    # print startup context JSON (debug)
```

The collector is a standalone script with no LLM dependency. Run it on a schedule (e.g. hourly cron) to keep data and signals fresh. Signal generation also runs at TUI startup for freshness.

### Signals

| Signal | Description |
|--------|-------------|
| `arbitrage` | Bracket YES prices not summing to ~100% — liquidity-weighted strength, fee-adjusted edge, per-leg spread/volume data. Filters out dead markets (no volume + wide spread). |

Signals are pre-computed attention flags injected into the agent at startup (top 10 by strength). The agent uses `active_markets.md` event groupings and semantic matching for cross-platform discovery — this is its core competency and better than any programmatic fuzzy matcher.

## Agent Tools

9 unified MCP tools across 2 servers (`mcp__markets__*` and `mcp__db__*`):

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

### Database Tools (1)

| Tool | Notes |
|------|-------|
| `recommend_trade` | Record an arbitrage recommendation with `thesis`, `estimated_edge_pct`, required `equivalence_notes` (settlement verification), and a `legs` array (2+ required). Each leg specifies exchange, market_id, action, side, quantity, price_cents. Schema enforces enums and numeric bounds. |

**Conventions:** All prices in cents (1-99). Actions: `buy`/`sell`. Sides: `yes`/`no`. Exchange: `kalshi` or `polymarket`.

## Recommendation Lifecycle

```
Agent recommends → TUI review → Execute or Reject
```

1. **Agent calls `recommend_trade`** — creates a recommendation group with 2+ legs in SQLite. Group-level fields: thesis, estimated edge, equivalence notes (required — settlement verification). Per-leg fields: exchange, market, action, side, quantity, price. Schema enforces enums (`kalshi`/`polymarket`, `buy`/`sell`, `yes`/`no`) and numeric bounds. Recommendations expire after `recommendation_ttl_minutes` (default 60).

2. **TUI displays pending groups** — sidebar on the dashboard (F1) and full review on the recommendations screen (F2). Shows edge, thesis, expiry countdown, and per-leg details.

3. **Execute** — confirmation modal shows order details and cost. On confirm, the TUI service layer validates position limits, places orders via the exchange clients per leg, logs trades for audit, and updates leg + group status.

4. **Reject** — marks all legs and the group as rejected. Visible in history.

## Analysis Flow

```
Discovery → Investigation → Verification → Sizing → Recommendation
```

1. **Discovery** — Agent reads `active_markets.md` (event-grouped with bracket price sums), pre-filters by spread/volume/DTE, finds cross-platform connections by category; also reviews pre-computed arbitrage signals
2. **Investigation** — Agent follows arb-specific protocol: match markets, verify settlement equivalence (5-point checklist), check orderbooks
3. **Verification** — Settlement equivalence verification (resolution source, timing, boundary conditions, conditional resolution, rounding), executable orderbook prices
4. **Sizing** — `normalize_prices.py` for fee-adjusted edge, orderbook depth for position size
5. **Recommendation** — Agent calls `recommend_trade` with all legs in one call, stored in DB for review

## Configuration

API credentials load from `.env` / environment variables via Pydantic `BaseSettings`. Trading parameters and agent settings are plain dataclasses — edit `config.py` to change defaults.

**Credentials** (from `.env` / env vars):

| Parameter | Env var |
|---|---|
| Kalshi API key ID | `KALSHI_API_KEY_ID` |
| Kalshi private key (PEM) | `KALSHI_PRIVATE_KEY` |
| Polymarket key ID | `POLYMARKET_KEY_ID` |
| Polymarket secret key | `POLYMARKET_SECRET_KEY` |

**Trading defaults** (in `config.py` — edit source to change):

| Parameter | Default |
|---|---|
| Kalshi max position | $100 |
| Polymarket max position | $50 |
| Max portfolio | $1,000 |
| Max contracts/order | 50 |
| Min edge required | 7% |
| Kalshi fee rate | 3% |
| Polymarket fee rate | 0% |
| Claude budget/session | $2 |
| Recommendation TTL | 60 min |

## Database Schema

SQLite (WAL mode) at `/workspace/data/agent.db`. Schema defined by SQLAlchemy ORM models in `models.py`, with Alembic autogenerate migrations (auto-run on startup). 9 tables:

| Table | Written by | Read by | Key columns |
|-------|-----------|---------|-------------|
| `market_snapshots` | collector | signals, agent | exchange, ticker, mid_price_cents, status |
| `events` | collector | signals, agent | (event_ticker, exchange) PK, markets_json |
| `signals` | signals | agent, TUI | scan_type, exchange, signal_strength, status |
| `trades` | TUI executor | agent, TUI | exchange, ticker, action, side, price_cents |
| `recommendation_groups` | agent | TUI | session_id, thesis, estimated_edge_pct, status |
| `recommendation_legs` | agent | TUI | group_id FK, exchange, market_id, action, side, price_cents |
| `portfolio_snapshots` | TUI | TUI | balance_usd, positions_json |
| `sessions` | main | agent, TUI | started_at, summary, trades_placed, recommendations_made |
| `watchlist` | agent (markdown) | — | (ticker, exchange) PK — agent now uses `/workspace/data/watchlist.md` instead |

## Workspace

```
/workspace/
  lib/
    normalize_prices.py   # Cross-platform price comparison with fee-adjusted edge
    match_markets.py      # Bulk title similarity matching across platforms
    kelly_size.py         # Kelly criterion position sizing
  analysis/               # Agent-written analysis (writable)
  data/
    agent.db              # SQLite database
    active_markets.md     # Enriched market listings: price, spread, vol, OI, DTE (generated by collector)
    watchlist.md          # Markets to monitor across sessions
    session.log           # Session scratch notes
  backups/                # DB backups (auto, max 7)
```

## Project Structure

```
src/finance_agent/
  main.py              # Entry point, SDK options, launches TUI
  config.py            # Credentials (env vars), TradingConfig + AgentConfig (source defaults)
  models.py            # SQLAlchemy ORM models (canonical schema for all 9 tables)
  database.py          # AgentDatabase: ORM queries, Alembic migration runner, backup
  tools.py             # Unified MCP tool factories (8 market + 1 DB)
  kalshi_client.py     # Kalshi SDK wrapper (batch, amend, paginated events)
  polymarket_client.py # Polymarket US SDK wrapper, intent maps
  hooks.py             # Recommendation counting, session lifecycle
  collector.py         # Market data collector (both platforms, market listings)
  signals.py           # Signal generator (bracket arbitrage with liquidity scoring)
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
      signals.py       # F4: signal table
      history.py       # F5: session history with drill-down
    widgets/
      agent_chat.py    # RichLog + Input with async streaming
      rec_card.py      # Single recommendation group card
      rec_list.py      # Recommendation group list
      portfolio_panel.py # Compact balance summary
      status_bar.py    # Session info bar
      ask_modal.py     # Agent question dialog
      confirm_modal.py # Order confirmation dialog
      orders_table.py  # Orders data table
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

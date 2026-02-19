# Finance Agent

Kalshi market analysis system built on the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-agent-sdk).

Discovers mispricings across Kalshi markets using a combination of programmatic analysis and semantic reasoning — reading settlement rules, identifying cross-market inconsistencies, and writing custom analytical scripts. Produces structured trade recommendations for review and execution via a terminal UI.

## Architecture

**Three-layer design:**

1. **Programmatic layer** (no LLM) — `collector.py` snapshots Kalshi market data to DuckDB, syncs daily history from S3, and upserts market metadata. Canonical views (`v_latest_markets`, `v_daily_with_meta`) provide SQL-native discovery.

2. **Agent layer** (Claude) — queries canonical DuckDB views for bulk market analysis using analytical SQL (window functions, `CORR()`, `QUALIFY`, `SAMPLE`, `ILIKE`), investigates candidates using MCP tools for semantic analysis (reading settlement rules, understanding market relationships), and records trade recommendations via `recommend_trade` with agent-specified positions per leg. Persists findings to a knowledge base across sessions.

3. **TUI layer** ([Textual](https://textual.textualize.io/)) — terminal interface embedding the agent chat alongside portfolio monitoring, recommendation review, and order execution. 4 navigable screens.

### TUI Screens

| Key | Screen | Purpose |
|-----|--------|---------|
| F1 | Dashboard | Agent chat (left) + portfolio summary & pending recs sidebar (right) |
| F2 | Recommendations | Full recommendation review with grouped execution and rejection |
| F3 | Portfolio | Balances, positions, resting orders, recent trades |
| F4 | History | Session list with drill-down to per-session trades and recommendations |

## Quickstart

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (for sandboxed execution)
- Kalshi API credentials (key ID + RSA private key)
- Anthropic API key

### Setup

```bash
git clone <repo-url> && cd finance-agent
uv sync --extra dev --extra skills

cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, KALSHI_API_KEY_ID, key path
```

### Run

```bash
make collect  # collect market data
make up       # build + run the TUI in Docker
```

## Data Pipeline

```bash
make collect    # snapshot markets + events to DuckDB, sync daily history, upsert metadata
make backup     # backup the database
make startup    # print startup context JSON (debug)
```

The collector is a standalone script with no LLM dependency. Run it on a schedule (e.g. hourly cron) to keep data fresh. The agent queries canonical DuckDB views and writes analytical SQL for historical analysis.

## Agent Tools

6 unified MCP tools across 2 servers (`mcp__markets__*` and `mcp__db__*`):

### Market Tools (5)

| Tool | Params | Notes |
|------|--------|-------|
| `get_market` | `market_id` | Full details, rules, settlement source |
| `get_orderbook` | `market_id`, `depth?` | Executable prices and depth |
| `get_trades` | `market_id`, `limit?` | Recent executions |
| `get_portfolio` | `include_fills?`, `include_settlements?` | Balances and positions |
| `get_orders` | `market_id?`, `status?` | Resting orders |

### Database Tools (1)

| Tool | Notes |
|------|-------|
| `recommend_trade` | Record a trade recommendation. Requires `thesis` and `legs` array (1+ required) with agent-specified action/side/quantity per leg. System validates limits and computes fees. |

**Conventions:** All prices in cents (1-99). Actions: `buy`/`sell`. Sides: `yes`/`no`.

## Recommendation Lifecycle

```
Agent recommends → TUI review → Execute or Reject
```

1. **Agent calls `recommend_trade`** — creates a recommendation group with 1+ legs in DuckDB. Agent specifies action, side, and quantity per leg; system validates position limits and computes fees.

2. **TUI displays pending groups** — sidebar on the dashboard (F1) and full review on the recommendations screen (F2). Shows edge, thesis, expiry countdown, and per-leg details.

3. **Execute** — confirmation modal shows order details and cost. On confirm, the TUI service layer validates position limits, places orders via the Kalshi client per leg, logs trades for audit, and updates leg + group status.

4. **Reject** — marks all legs and the group as rejected. Visible in history.

## Analysis Approach

The agent combines programmatic analysis with semantic reasoning:

1. **Programmatic discovery** — queries canonical DuckDB views and writes analytical SQL to find numerical anomalies (price inconsistencies, correlation divergences, stale markets, volume spikes)
2. **Semantic investigation** — reads settlement rules and market descriptions via `get_market` to understand edge cases, resolution criteria, and cross-market relationships
3. **Hypothesis and validation** — forms a thesis about why a mispricing exists, validates with orderbook depth and trade activity
4. **Cumulative learning** — records findings, rejected ideas, and heuristics in a persistent knowledge base

## Configuration

API credentials load from `.env` / environment variables via Pydantic `BaseSettings`. Trading parameters and agent settings are plain dataclasses — edit `config.py` to change defaults.

**Credentials** (from `.env` / env vars):

| Parameter | Env var |
|---|---|
| Kalshi API key ID | `KALSHI_API_KEY_ID` |
| Kalshi private key (PEM) | `KALSHI_PRIVATE_KEY` |

**Trading defaults** (in `config.py` — edit source to change):

| Parameter | Default |
|---|---|
| Kalshi max position | $100 |
| Max portfolio | $1,000 |
| Max contracts/order | 50 |
| Claude budget/session | $2 |
| Recommendation TTL | 60 min |

**Docker path overrides** (set in `docker-compose.yml`):

| Env var | Default | Docker value |
|---|---|---|
| `FA_DB_PATH` | `workspace/data/agent.duckdb` | `/app/state/agent.duckdb` |
| `FA_BACKUP_DIR` | `workspace/backups` | `/app/state/backups` |
| `FA_LOG_FILE` | *(none)* | `/app/state/agent.log` |

## Database Schema

DuckDB at `/workspace/data/agent.duckdb`. Schema defined by SQLAlchemy ORM models in `models.py` via `duckdb_engine`, with Alembic migrations (auto-run on startup). Three canonical views (`v_latest_markets`, `v_daily_with_meta`, `v_active_recommendations`) are created after migrations. `maintenance()` runs `CHECKPOINT` (and optionally `VACUUM ANALYZE`) after collector/backfill. 8 tables:

| Table | Written by | Read by | Key columns |
|-------|-----------|---------|-------------|
| `market_snapshots` | collector | agent | exchange, ticker, mid_price_cents, status |
| `events` | collector | agent | (event_ticker, exchange) PK, markets_json |
| `trades` | TUI executor | agent, TUI | exchange, ticker, action, side, quantity, leg_id FK |
| `recommendation_groups` | agent | TUI | session_id FK, thesis, estimated_edge_pct, status |
| `recommendation_legs` | agent | TUI | group_id FK, exchange, market_id, action, side, price_cents |
| `sessions` | main | agent, TUI | started_at, summary, trades_placed, recommendations_made |
| `kalshi_daily` | collector (S3) | agent scripts | date, ticker_name, high, low, daily_volume, open_interest. **Very large** (~100M+ rows). |
| `kalshi_market_meta` | collector | agent scripts | ticker PK, title, category, event_ticker, first_seen. **Partial index** (~30K recently-active tickers, not all historical). |

## Workspace

The workspace uses a dual-mount isolation pattern. Reference scripts are COPY'd into the Docker image (immutable). Runtime data is mounted read-only for the agent, with app code writing through a separate path (`/app/state/`) outside the agent's sandbox.

```
/workspace/                     # agent sandbox (cwd)
  scripts/                      # COPY'd into image (read-only)
    db_utils.py                 # Shared DuckDB query helpers (query() with auto-LIMIT)
    correlations.py             # Pairwise correlations using DuckDB CORR() aggregate
    query_history.py            # Daily history queries via v_daily_with_meta view
    market_info.py              # Full market lookup across all tables
    category_overview.py        # Category summary via v_latest_markets view
    query_recommendations.py    # Recommendation history queries with leg details
    schema_reference.md         # Database schema reference (views, DuckDB features, guardrails)
  data/                         # :ro mount (kernel-enforced read-only for agent)
    agent.duckdb                # DuckDB database
  analysis/                     # :rw mount (agent's writable scratch space)
    knowledge_base.md           # Persistent memory (watchlist, findings, patterns)
```

## Project Structure

```
src/finance_agent/
  main.py              # Entry point, SDK options, launches TUI
  config.py            # Credentials (env vars), TradingConfig + AgentConfig (source defaults)
  constants.py         # Shared string constants (exchanges, statuses, sides, actions, strategies)
  models.py            # SQLAlchemy ORM models + DuckDB Sequences (canonical schema for all 8 tables)
  database.py          # AgentDatabase: DuckDB via duckdb_engine, ORM queries, canonical views, backup
  tools.py             # Unified MCP tool factories (5 market + 1 DB = 6 tools)
  fees.py              # Kalshi fee calculations (P(1-P) formula)
  kalshi_client.py     # Kalshi SDK wrapper (batch, amend, paginated events)
  polymarket_client.py # Dormant: Polymarket US SDK wrapper (preserved for future)
  hooks.py             # File protection, recommendation counting, session lifecycle
  collector.py         # Kalshi market data collector
  backfill.py          # Kalshi daily history sync from S3
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
      history.py       # F4: session history with drill-down
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
make shell              # bash into container
uv run pre-commit run --all-files
```

Ruff for linting/formatting (line length 99, Python 3.12 target), mypy for type checking. Pre-commit hooks enforce both.

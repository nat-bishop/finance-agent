# Database Schema Reference

SQLite database at `/workspace/data/agent.db`. All timestamps are ISO 8601 UTC. Prices in cents.

## Table Sizes (approximate)

| Table | Rows | Notes |
|-------|------|-------|
| `kalshi_daily` | ~100M+ | **Very large.** Always filter by `ticker_name`. Date-only scans ~10s. |
| `market_snapshots` | ~200K | Moderate. Use `latest_snapshot_ids()` helper for latest-per-ticker. |
| `kalshi_market_meta` | ~30K | Small. Use as discovery index for historical queries. |
| `events` | ~8K | Small. Fast for all queries. |
| `recommendation_groups` | Small | Grows with agent usage. |
| `recommendation_legs` | Small | Grows with agent usage. |
| `trades` | Small | Grows with execution. |
| `sessions` | Small | One row per agent session. |

## Query Performance Guide

### kalshi_daily (139M rows)
- **ALWAYS** filter by `ticker_name` (indexed via `idx_kalshi_daily_ticker`). Date-only scans: ~10s.
- No `title` column — join to `kalshi_market_meta` for titles.
- No `close` column — use `(high + low) / 2` as midprice proxy.
- Anti-pattern: `SELECT ... FROM kalshi_daily WHERE date >= '2026-01-01'`
- Correct: `SELECT ... FROM kalshi_daily WHERE ticker_name IN (...) AND date >= '2026-01-01'`

### Discovery: meta -> daily
- Search `kalshi_market_meta` first (30K rows, instant for any query).
- Collect tickers, then batch-query `kalshi_daily` with `WHERE ticker_name IN (...)`.
- Anti-pattern: `FROM kalshi_daily d JOIN kalshi_market_meta m ... WHERE m.title LIKE '%word%'`
- Correct: Two queries — meta for tickers, then daily for those tickers.

### Batch fetching (avoid N+1)
- `query()` opens/closes a connection each call — minimize call count.
- Anti-pattern: `for ticker in tickers: query("... WHERE ticker_name = ?", (ticker,))`
- Correct: `query("... WHERE ticker_name IN (...)", tuple(tickers))`

### market_snapshots latest-per-ticker
- In WHERE clauses: `AND id IN ({latest_snapshot_ids()})` is fine.
- In JOIN ON clauses: `IN(subquery)` is evaluated per-row — use temp table instead.
- Anti-pattern: `LEFT JOIN market_snapshots s ON ... AND s.id IN (SELECT MAX(id) ...)`
- Correct: `materialize_latest_ids(conn)` then `JOIN _latest_ids li ON s.id = li.id`

### Analytics: compute in Python, not SQL
- Fetch raw data with a simple query, compute rolling stats in Python.
- Anti-pattern: `JOIN kalshi_daily b ON a.ticker_name = b.ticker_name AND b.date BETWEEN ...`
- Correct: Fetch ordered rows, compute moving averages / z-scores / correlations with Python loops.

### Pairwise operations
- Cap at ~200 tickers for O(N^2) work (correlations, distance matrices).
- 200 = 20K pairs (fast). 500 = 125K pairs (slow). 1000+ = minutes.

### events (8K rows)
- Small table, fast for any query pattern.

## Tables

### market_snapshots
Point-in-time market data from collector.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| captured_at | TEXT | ISO timestamp |
| source | TEXT | Default "collector" |
| exchange | TEXT | Default "kalshi" |
| ticker | TEXT | Market ticker |
| event_ticker | TEXT | Parent event |
| series_ticker | TEXT | Parent series |
| title | TEXT | Market title |
| category | TEXT | Category |
| status | TEXT | "open", "closed", etc. |
| yes_bid | INTEGER | Best YES bid (cents) |
| yes_ask | INTEGER | Best YES ask (cents) |
| no_bid | INTEGER | Best NO bid (cents) |
| no_ask | INTEGER | Best NO ask (cents) |
| last_price | INTEGER | Last trade price (cents) |
| volume | INTEGER | Total volume |
| volume_24h | INTEGER | 24h volume |
| open_interest | INTEGER | Open contracts |
| spread_cents | INTEGER | yes_ask - yes_bid |
| mid_price_cents | INTEGER | (yes_bid + yes_ask) / 2 |
| implied_probability | REAL | Mid-price as probability |
| days_to_expiration | REAL | Days until close |
| close_time | TEXT | Market close timestamp |
| settlement_value | INTEGER | Settlement price (cents, if settled) |
| markets_in_event | INTEGER | Number of markets in parent event |
| raw_json | TEXT | Full API response JSON |

**Indexes:**
- `idx_snapshots_ticker_time(ticker, captured_at)`
- `idx_snapshots_series(series_ticker)`
- `idx_snapshots_category(category)`
- `idx_snapshots_latest(status, exchange, ticker, captured_at)` — used by latest-per-ticker queries

### events
Event structure (one event has multiple markets).

| Column | Type | Description |
|--------|------|-------------|
| event_ticker | TEXT PK | Event ID |
| exchange | TEXT PK | Default "kalshi" |
| series_ticker | TEXT | Parent series |
| title | TEXT | Event title |
| category | TEXT | Category |
| mutually_exclusive | INTEGER | 1 if outcomes are mutually exclusive |
| last_updated | TEXT | Last collection timestamp |
| markets_json | TEXT | JSON array of nested market summaries |

### kalshi_daily
Daily EOD data from Kalshi public S3. History back to 2021-06-30. **Very large table** — always filter by `ticker_name`.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| date | TEXT | YYYY-MM-DD |
| ticker_name | TEXT | Market ticker |
| report_ticker | TEXT | S3 reporting ticker |
| payout_type | TEXT | Payout type |
| open_interest | INTEGER | EOD open interest |
| daily_volume | INTEGER | Day's volume |
| block_volume | INTEGER | Block trade volume |
| high | INTEGER | Daily high (cents) |
| low | INTEGER | Daily low (cents) |
| status | TEXT | Market status |

No `close` column — use `(high + low) / 2` as midprice proxy.

**Indexes:**
- `idx_kalshi_daily_unique(date, ticker_name)` UNIQUE
- `idx_kalshi_daily_ticker(ticker_name)` — use this for single-ticker lookups
- `idx_kalshi_daily_report(report_ticker)`

### kalshi_market_meta
Partial metadata catalog for recently-active markets. **Does NOT cover all historical tickers** — only markets seen by the collector during `make collect`. Use as discovery index for historical queries.

| Column | Type | Description |
|--------|------|-------------|
| ticker | TEXT PK | Market ticker |
| event_ticker | TEXT | Parent event |
| series_ticker | TEXT | Parent series |
| title | TEXT | Market title |
| category | TEXT | Category |
| first_seen | TEXT | First collection date |
| last_seen | TEXT | Most recent collection date |

**Indexes:**
- `idx_meta_series(series_ticker)`
- `idx_meta_category(category)`

### recommendation_groups
Agent trade recommendations (grouped legs).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| session_id | TEXT FK | -> sessions.id |
| created_at | TEXT | ISO timestamp |
| thesis | TEXT | Agent's reasoning |
| equivalence_notes | TEXT | Market relationship notes |
| estimated_edge_pct | REAL | Agent's edge estimate |
| status | TEXT | pending/executed/rejected/partial |
| expires_at | TEXT | TTL expiration timestamp |
| reviewed_at | TEXT | When user reviewed |
| executed_at | TEXT | When executed |
| total_exposure_usd | REAL | Total capital deployed |
| computed_edge_pct | REAL | System-computed edge (bracket only) |
| computed_fees_usd | REAL | System-computed total fees |
| strategy | TEXT | "bracket" or "manual" |

**Indexes:**
- `idx_group_status(status)`
- `idx_rec_session(session_id)`
- `idx_group_created_at(created_at)`

### recommendation_legs
Individual legs within a recommendation group.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| group_id | INTEGER FK | -> recommendation_groups.id |
| leg_index | INTEGER | Order in group (0-based) |
| exchange | TEXT | Exchange name |
| market_id | TEXT | Market ticker |
| market_title | TEXT | Market title at recommendation time |
| action | TEXT | buy/sell |
| side | TEXT | yes/no |
| quantity | INTEGER | Contracts |
| price_cents | INTEGER | Price at recommendation time |
| order_type | TEXT | Default "limit" |
| status | TEXT | pending/placed/executed/partial/rejected |
| order_id | TEXT | Exchange order ID (after placement) |
| executed_at | TEXT | Execution timestamp |
| is_maker | BOOLEAN | True if shallowest depth (lower fees) |
| fill_price_cents | INTEGER | Actual execution price |
| fill_quantity | INTEGER | Actual quantity filled |
| orderbook_snapshot_json | TEXT | JSON: {yes_ask, no_ask, yes_depth, no_depth} |

**Indexes:**
- `idx_leg_group(group_id)`

### trades
Executed trades logged by TUI.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| session_id | TEXT FK | -> sessions.id |
| leg_id | INTEGER FK | -> recommendation_legs.id |
| exchange | TEXT | Exchange name |
| timestamp | TEXT | ISO execution timestamp |
| ticker | TEXT | Market ticker |
| action | TEXT | buy/sell |
| side | TEXT | yes/no |
| quantity | INTEGER | Contracts |
| price_cents | INTEGER | Execution price |
| order_type | TEXT | Order type |
| order_id | TEXT | Exchange order ID |
| status | TEXT | Trade status |
| result_json | TEXT | Full exchange response |

**Indexes:**
- `idx_trades_ticker(ticker)`
- `idx_trades_session(session_id)`
- `idx_trades_status(status)`

### sessions
Agent session tracking.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | 8-char random ID |
| started_at | TEXT | ISO timestamp |
| ended_at | TEXT | ISO timestamp |
| summary | TEXT | Session summary |
| trades_placed | INTEGER | Count of trades executed |
| recommendations_made | INTEGER | Count of recommendations |
| pnl_usd | REAL | Session P&L |

**Indexes:**
- `idx_sessions_ended_at(ended_at)`

## Useful Joins

```sql
-- Daily history with titles (start from meta, JOIN to daily)
SELECT d.date, d.ticker_name, m.title, m.category, d.high, d.low, d.daily_volume
FROM kalshi_market_meta m
JOIN kalshi_daily d ON m.ticker = d.ticker_name
WHERE m.category = 'Politics'
ORDER BY d.date DESC;

-- Latest snapshot per ticker (use db_utils.latest_snapshots() helper)
SELECT * FROM market_snapshots
WHERE status = 'open' AND exchange = 'kalshi'
  AND id IN (SELECT MAX(id) FROM market_snapshots WHERE status = 'open' GROUP BY ticker);

-- Bracket candidates (mutually exclusive events with markets)
SELECT e.event_ticker, e.title, e.category, COUNT(DISTINCT s.ticker) as n_markets
FROM events e
JOIN market_snapshots s ON s.event_ticker = e.event_ticker AND s.exchange = 'kalshi'
WHERE e.mutually_exclusive = 1 AND s.status = 'open'
  AND s.id IN (SELECT MAX(id) FROM market_snapshots WHERE status = 'open' GROUP BY ticker)
GROUP BY e.event_ticker
HAVING n_markets >= 2;

-- Recommendation history with legs
SELECT rg.id, rg.created_at, rg.thesis, rg.strategy, rg.status,
       rg.computed_edge_pct, rg.total_exposure_usd,
       rl.market_id, rl.market_title, rl.action, rl.side, rl.quantity, rl.price_cents
FROM recommendation_groups rg
JOIN recommendation_legs rl ON rl.group_id = rg.id
ORDER BY rg.created_at DESC;

-- Search historical tickers by keyword (start from meta)
SELECT m.ticker, m.title, m.category, COUNT(d.id) as data_points
FROM kalshi_market_meta m
LEFT JOIN kalshi_daily d ON m.ticker = d.ticker_name
WHERE m.title LIKE '%inflation%'
GROUP BY m.ticker
ORDER BY data_points DESC;
```

## Common Mistakes

```sql
-- BAD: Full table scan on kalshi_daily (no ticker filter, ~10s)
SELECT ticker_name, AVG(daily_volume)
FROM kalshi_daily WHERE date >= '2026-01-01'
GROUP BY ticker_name;

-- BAD: Self-join for rolling average (catastrophically slow)
SELECT a.*, AVG(b.high) as ma_30
FROM kalshi_daily a
JOIN kalshi_daily b ON a.ticker_name = b.ticker_name
  AND b.date BETWEEN date(a.date, '-30 days') AND a.date
GROUP BY a.id;

-- BAD: IN(subquery) inside LEFT JOIN ON (per-row evaluation, >2min)
LEFT JOIN market_snapshots s ON s.event_ticker = e.event_ticker
  AND s.id IN (SELECT MAX(id) FROM market_snapshots
               WHERE status = 'open' GROUP BY ticker);
-- FIX: use materialize_latest_ids(conn) then JOIN _latest_ids

-- BAD: N+1 queries in a loop
-- for ticker in tickers:
--     query("SELECT ... FROM kalshi_daily WHERE ticker_name = ?", (ticker,))
-- FIX: batch with WHERE ticker_name IN (?,?,...)
```

# Database Schema Reference

DuckDB database at `/workspace/data/agent.duckdb`. All timestamps are ISO 8601 UTC. Prices in cents.

## Table Sizes (approximate)

| Table | Rows | Notes |
|-------|------|-------|
| `kalshi_daily` | ~100M+ | **Very large.** Use `v_daily_with_meta` view or filter by `ticker_name`. |
| `market_snapshots` | ~200K | Moderate. Use `v_latest_markets` view for latest-per-ticker. |
| `kalshi_market_meta` | ~30K | Small. Use as discovery index for historical queries. |
| `events` | ~8K | Small. Fast for all queries. |
| `recommendation_groups` | Small | Grows with agent usage. |
| `recommendation_legs` | Small | Grows with agent usage. |
| `trades` | Small | Grows with execution. |
| `sessions` | Small | One row per agent session. |

## Canonical Views

### `v_latest_markets` — market discovery (replaces markets.jsonl)
Latest snapshot per open ticker with event metadata and description. Use for all market discovery queries.

| Column | Type | Description |
|--------|------|-------------|
| `exchange` | TEXT | Always "kalshi" |
| `ticker` | TEXT | Market ticker — use with tools |
| `event_ticker` | TEXT | Parent event ID |
| `event_title` | TEXT | Parent event title |
| `mutually_exclusive` | INTEGER | 1 if event markets are mutually exclusive |
| `title` | TEXT | Market title/question |
| `description` | TEXT | Settlement rules text (extracted from raw_json) |
| `category` | TEXT | Market category |
| `mid_price_cents` | INTEGER | Mid-price in cents |
| `spread_cents` | INTEGER | Bid-ask spread in cents |
| `yes_bid` | INTEGER | Best bid (cents) |
| `yes_ask` | INTEGER | Best ask (cents) |
| `volume_24h` | INTEGER | 24-hour volume |
| `open_interest` | INTEGER | Open interest |
| `days_to_expiration` | FLOAT | Days until expiry |
| `close_time` | TEXT | Market close timestamp |
| `captured_at` | TEXT | When data was captured |

### `v_daily_with_meta` — safe historical data entry point
Daily history joined with metadata. The INNER JOIN to `kalshi_market_meta` naturally limits results to tickers with metadata, preventing accidental full scans of `kalshi_daily`.

**Coverage limitation**: This view only returns rows for tickers present in `kalshi_market_meta`. Expired/settled markets may not have metadata entries. For maximum historical coverage, query `kalshi_daily` directly with a `ticker_name` LIKE filter. Use `report_ticker` as the event grouping key.
```sql
-- Example: all Rotten Tomatoes historical data (including expired markets)
SELECT date, ticker_name, report_ticker, high, low, daily_volume, open_interest
FROM kalshi_daily WHERE ticker_name LIKE 'KXRT%'
ORDER BY report_ticker, ticker_name, date
```

| Column | Type | Description |
|--------|------|-------------|
| `date` | TEXT | YYYY-MM-DD |
| `ticker_name` | TEXT | Market ticker |
| `title` | TEXT | Market title (from meta) |
| `category` | TEXT | Category (from meta) |
| `event_ticker` | TEXT | Parent event (from meta) |
| `high` | INTEGER | Daily high (cents) |
| `low` | INTEGER | Daily low (cents) |
| `daily_volume` | INTEGER | Day's volume |
| `open_interest` | INTEGER | EOD open interest |
| `status` | TEXT | Market status |

### `v_active_recommendations` — pending recommendations with legs
All pending recommendation groups with their legs. Use for monitoring active recommendations.

| Column | Type | Description |
|--------|------|-------------|
| `group_id` | INTEGER | Recommendation group ID |
| `thesis` | TEXT | Agent's reasoning |
| `strategy` | TEXT | "manual" |
| `group_status` | TEXT | Always "pending" |
| `estimated_edge_pct` | FLOAT | Agent's edge estimate |
| `total_exposure_usd` | FLOAT | Total capital deployed |
| `created_at` | TEXT | ISO timestamp |
| `expires_at` | TEXT | TTL expiration |
| `leg_index` | INTEGER | Order in group (0-based) |
| `exchange` | TEXT | Exchange name |
| `market_id` | TEXT | Market ticker |
| `market_title` | TEXT | Market title |
| `action` | TEXT | buy/sell |
| `side` | TEXT | yes/no |
| `quantity` | INTEGER | Contracts |
| `price_cents` | INTEGER | Price at recommendation time |
| `leg_status` | TEXT | Leg status |

## DuckDB Features

### QUALIFY — filter window results without subqueries
```sql
SELECT * FROM market_snapshots WHERE status = 'open'
QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY captured_at DESC) = 1
```

### SAMPLE — explore large tables safely
```sql
SELECT * FROM kalshi_daily USING SAMPLE 1000 ROWS
SELECT * FROM kalshi_daily USING SAMPLE 1%
```

### Built-in analytics
```sql
-- Correlation
SELECT CORR(a.mid, b.mid) FROM ...

-- Rolling average
AVG(high) OVER (PARTITION BY ticker_name ORDER BY date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)

-- Percentiles
PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY spread_cents)
```

### ILIKE — case-insensitive pattern matching
```sql
SELECT * FROM kalshi_market_meta WHERE title ILIKE '%inflation%'
```

### Date functions
```sql
date_trunc('month', CAST(date AS DATE))
date_diff('day', CAST(date AS DATE), current_date)
```

## Guardrails — Large Table Safety

- **`kalshi_daily` (100M+ rows)**: Always query through `v_daily_with_meta` or filter by `ticker_name`. Use `SAMPLE` for exploration. Unbounded `SELECT * FROM kalshi_daily` returns 100M+ rows.
- **`market_snapshots` (~200K rows)**: Use `v_latest_markets` instead of querying directly.
- **Always add `LIMIT`** on exploratory queries.

## Tables

### market_snapshots
Point-in-time market data from collector.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment (sequence) |
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
| implied_probability | FLOAT | Mid-price as probability |
| days_to_expiration | FLOAT | Days until close |
| close_time | TEXT | Market close timestamp |
| settlement_value | INTEGER | Settlement price (cents, if settled) |
| markets_in_event | INTEGER | Number of markets in parent event |
| raw_json | TEXT | Full API response JSON |

**Indexes:** `idx_snapshots_ticker_time`, `idx_snapshots_series`, `idx_snapshots_category`, `idx_snapshots_latest`

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
Daily EOD data from Kalshi public S3. History back to 2021-06-30. **Very large table** — use `v_daily_with_meta` view or filter by `ticker_name`.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment (sequence) |
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

**Indexes:** `idx_kalshi_daily_ticker(ticker_name)`, `idx_kalshi_daily_report(report_ticker)`
**Constraints:** `uq_kalshi_daily_date_ticker(date, ticker_name)` UNIQUE

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

**Indexes:** `idx_meta_series(series_ticker)`, `idx_meta_category(category)`

### recommendation_groups
Agent trade recommendations (grouped legs).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment (sequence) |
| session_id | TEXT FK | -> sessions.id |
| created_at | TEXT | ISO timestamp |
| thesis | TEXT | Agent's reasoning |
| equivalence_notes | TEXT | Market relationship notes |
| estimated_edge_pct | FLOAT | Agent's edge estimate |
| status | TEXT | pending/executed/rejected/partial |
| expires_at | TEXT | TTL expiration timestamp |
| reviewed_at | TEXT | When user reviewed |
| executed_at | TEXT | When executed |
| total_exposure_usd | FLOAT | Total capital deployed |
| computed_edge_pct | FLOAT | System-computed edge |
| computed_fees_usd | FLOAT | System-computed total fees |
| strategy | TEXT | "manual" |
| hypothetical_pnl_usd | FLOAT | Computed P&L after settlement |

**Indexes:** `idx_group_status`, `idx_rec_session`, `idx_group_created_at`

### recommendation_legs
Individual legs within a recommendation group.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment (sequence) |
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
| settlement_value | INTEGER | Settlement price (cents, if settled) |
| settled_at | TEXT | Settlement timestamp |

**Indexes:** `idx_leg_group(group_id)`

### trades
Executed trades logged by TUI.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment (sequence) |
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

**Indexes:** `idx_trades_ticker`, `idx_trades_session`, `idx_trades_status`

### sessions
Agent session tracking.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | 8-char random ID |
| started_at | TEXT | ISO timestamp |

## Useful Queries

```sql
-- Market discovery (replaces markets.jsonl)
SELECT ticker, title, category, mid_price_cents, spread_cents, volume_24h
FROM v_latest_markets
WHERE category = 'Politics' AND spread_cents < 5
ORDER BY volume_24h DESC;

-- Historical analysis with titles
SELECT date, ticker_name, title, high, low, daily_volume
FROM v_daily_with_meta
WHERE ticker_name = 'KX-FOO' AND date >= '2025-01-01'
ORDER BY date;

-- Correlated markets (DuckDB native)
SELECT a.ticker_name, b.ticker_name, CORR(a.mid, b.mid) as correlation
FROM (SELECT ticker_name, date, (high+low)/2 as mid FROM v_daily_with_meta WHERE category = 'Politics') a
JOIN (SELECT ticker_name, date, (high+low)/2 as mid FROM v_daily_with_meta WHERE category = 'Politics') b
  ON a.date = b.date AND a.ticker_name < b.ticker_name
GROUP BY 1, 2
HAVING ABS(CORR(a.mid, b.mid)) >= 0.7;

-- Rolling 30-day average
SELECT ticker_name, date, high,
       AVG(high) OVER (PARTITION BY ticker_name ORDER BY date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) as ma_30
FROM v_daily_with_meta
WHERE ticker_name = 'KX-FOO';

-- Pending recommendations
SELECT * FROM v_active_recommendations;

-- Explore large table safely
SELECT * FROM kalshi_daily USING SAMPLE 1000 ROWS;
```

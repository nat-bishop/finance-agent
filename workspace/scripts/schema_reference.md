# Database Schema Reference

SQLite database at `/workspace/data/agent.db`. All timestamps are ISO 8601 UTC.

## Tables

### market_snapshots
Point-in-time market data from collector.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| captured_at | TEXT | ISO timestamp |
| exchange | TEXT | Always "kalshi" |
| ticker | TEXT | Market ticker |
| event_ticker | TEXT | Parent event |
| title | TEXT | Market title |
| category | TEXT | Category |
| status | TEXT | "open", "closed", etc. |
| yes_bid / yes_ask | INTEGER | Best bid/ask (cents) |
| no_bid / no_ask | INTEGER | Best NO bid/ask (cents) |
| mid_price_cents | INTEGER | (yes_bid + yes_ask) / 2 |
| spread_cents | INTEGER | yes_ask - yes_bid |
| volume_24h | INTEGER | 24h volume |
| open_interest | INTEGER | Open contracts |
| days_to_expiration | REAL | Days until close |

**Key index**: `idx_snapshots_latest(status, exchange, ticker, captured_at)`

### events
Event structure (one event has multiple markets).

| Column | Type | Description |
|--------|------|-------------|
| event_ticker | TEXT PK | Event ID |
| exchange | TEXT PK | Always "kalshi" |
| title | TEXT | Event title |
| category | TEXT | Category |
| mutually_exclusive | INTEGER | 1 if outcomes are mutually exclusive |
| markets_json | TEXT | JSON array of nested market summaries |

### kalshi_daily
Daily EOD data from Kalshi public S3. History back to 2021-06-30.

| Column | Type | Description |
|--------|------|-------------|
| date | TEXT | YYYY-MM-DD |
| ticker_name | TEXT | Market ticker |
| high / low | INTEGER | Daily high/low (cents) |
| daily_volume | INTEGER | Day's volume |
| open_interest | INTEGER | EOD open interest |

**Unique index**: `(date, ticker_name)`

### kalshi_market_meta
Permanent metadata catalog. Never purged.

| Column | Type | Description |
|--------|------|-------------|
| ticker | TEXT PK | Market ticker |
| event_ticker | TEXT | Parent event |
| title | TEXT | Market title |
| category | TEXT | Category |
| first_seen / last_seen | TEXT | Collection dates |

### recommendation_groups
Agent trade recommendations (grouped legs).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| session_id | TEXT FK | -> sessions.id |
| thesis | TEXT | Agent's reasoning |
| equivalence_notes | TEXT | Market relationship |
| status | TEXT | pending/executed/rejected/partial |
| total_exposure_usd | REAL | Total capital |
| computed_edge_pct | REAL | System-computed edge |

### recommendation_legs
Individual legs within a recommendation group.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| group_id | INTEGER FK | -> recommendation_groups.id |
| market_id | TEXT | Market ticker |
| action | TEXT | buy/sell |
| side | TEXT | yes/no |
| quantity | INTEGER | Contracts |
| price_cents | INTEGER | Price at recommendation time |

### trades
Executed trades logged by TUI.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| session_id | TEXT FK | -> sessions.id |
| leg_id | INTEGER FK | -> recommendation_legs.id |
| ticker | TEXT | Market ticker |
| action | TEXT | buy/sell |
| side | TEXT | yes/no |
| quantity | INTEGER | Contracts |
| price_cents | INTEGER | Execution price |
| order_id | TEXT | Exchange order ID |

### sessions
Agent session tracking.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | 8-char random ID |
| started_at / ended_at | TEXT | ISO timestamps |
| summary | TEXT | Session summary |

## Useful Joins

```sql
-- Daily history with titles
SELECT d.date, d.ticker_name, m.title, m.category, d.high, d.low, d.daily_volume
FROM kalshi_daily d
JOIN kalshi_market_meta m ON d.ticker_name = m.ticker
WHERE m.category = 'Politics'
ORDER BY d.date DESC;

-- Latest snapshot per ticker
SELECT * FROM market_snapshots
WHERE status = 'open' AND exchange = 'kalshi'
  AND id IN (SELECT MAX(id) FROM market_snapshots WHERE status = 'open' GROUP BY ticker);

-- Bracket candidates (mutually exclusive events with markets)
SELECT e.event_ticker, e.title, e.category, COUNT(s.ticker) as n_markets
FROM events e
JOIN market_snapshots s ON s.event_ticker = e.event_ticker AND s.exchange = 'kalshi'
WHERE e.mutually_exclusive = 1 AND s.status = 'open'
GROUP BY e.event_ticker
HAVING n_markets >= 2;
```

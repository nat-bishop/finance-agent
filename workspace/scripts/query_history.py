"""Query Kalshi daily history with metadata join.

Usage:
    python query_history.py TICKER [--days N]
    python query_history.py --search "keyword" [--days N]
"""
import argparse
import json
from db_utils import query


def get_history(ticker, days=90):
    """Get daily history for a specific ticker using v_daily_with_meta."""
    return query(
        """
        SELECT date, ticker_name, title, category,
               high, low, daily_volume, open_interest, status
        FROM v_daily_with_meta
        WHERE ticker_name = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (ticker, days),
        limit=0,
    )


def search_tickers(keyword, days=30):
    """Search for tickers matching a keyword in title (case-insensitive)."""
    return query(
        """
        SELECT DISTINCT m.ticker, m.title, m.category, m.event_ticker,
               COUNT(d.id) as data_points,
               MAX(d.date) as last_date,
               MAX(d.daily_volume) as max_volume
        FROM kalshi_market_meta m
        LEFT JOIN kalshi_daily d ON m.ticker = d.ticker_name
        WHERE m.title ILIKE ?
        GROUP BY m.ticker, m.title, m.category, m.event_ticker
        ORDER BY max_volume DESC NULLS LAST
        LIMIT 50
        """,
        (f"%{keyword}%",),
        limit=0,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query Kalshi daily history")
    parser.add_argument("ticker", nargs="?", help="Market ticker")
    parser.add_argument("--search", help="Search keyword in titles")
    parser.add_argument("--days", type=int, default=90, help="Days of history")
    args = parser.parse_args()

    if args.search:
        results = search_tickers(args.search, args.days)
        for r in results:
            print(json.dumps(r, default=str))
    elif args.ticker:
        results = get_history(args.ticker, args.days)
        for r in results:
            print(json.dumps(r, default=str))
    else:
        parser.print_help()

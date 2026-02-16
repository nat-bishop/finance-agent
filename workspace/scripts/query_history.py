"""Query Kalshi daily history with metadata join.

Usage:
    python query_history.py TICKER [--days N]
    python query_history.py --search "keyword" [--days N]
"""
import argparse
import json
from db_utils import query


def get_history(ticker, days=90):
    """Get daily history for a specific ticker."""
    return query(
        """
        SELECT d.date, d.ticker_name, m.title, m.category,
               d.high, d.low, d.daily_volume, d.open_interest, d.status
        FROM kalshi_daily d
        LEFT JOIN kalshi_market_meta m ON d.ticker_name = m.ticker
        WHERE d.ticker_name = ?
        ORDER BY d.date DESC
        LIMIT ?
        """,
        (ticker, days),
    )


def search_tickers(keyword, days=30):
    """Search for tickers matching a keyword in title."""
    return query(
        """
        SELECT DISTINCT m.ticker, m.title, m.category, m.event_ticker,
               COUNT(d.id) as data_points,
               MAX(d.date) as last_date,
               MAX(d.daily_volume) as max_volume
        FROM kalshi_market_meta m
        LEFT JOIN kalshi_daily d ON m.ticker = d.ticker_name
        WHERE m.title LIKE ?
        GROUP BY m.ticker
        ORDER BY max_volume DESC NULLS LAST
        LIMIT 50
        """,
        (f"%{keyword}%",),
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

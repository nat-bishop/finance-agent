"""Full market lookup across all tables.

Usage:
    python market_info.py TICKER
"""
import argparse
import json
from db_utils import query


def lookup(ticker):
    """Get all available data for a market ticker."""
    result = {}

    snapshots = query(
        "SELECT * FROM market_snapshots WHERE ticker = ? ORDER BY captured_at DESC LIMIT 1",
        (ticker,),
        limit=0,
    )
    if snapshots:
        result["snapshot"] = snapshots[0]

    meta = query(
        "SELECT * FROM kalshi_market_meta WHERE ticker = ?",
        (ticker,),
        limit=0,
    )
    if meta:
        result["meta"] = meta[0]

    if snapshots and snapshots[0].get("event_ticker"):
        events = query(
            "SELECT * FROM events WHERE event_ticker = ? AND exchange = 'kalshi'",
            (snapshots[0]["event_ticker"],),
            limit=0,
        )
        if events:
            result["event"] = events[0]

    daily = query(
        """
        SELECT date, high, low, daily_volume, open_interest, status
        FROM kalshi_daily WHERE ticker_name = ? ORDER BY date DESC LIMIT 30
        """,
        (ticker,),
        limit=0,
    )
    if daily:
        result["daily_history"] = daily

    trades = query(
        "SELECT * FROM trades WHERE ticker = ? ORDER BY timestamp DESC LIMIT 10",
        (ticker,),
        limit=0,
    )
    if trades:
        result["trades"] = trades

    legs = query(
        """
        SELECT rl.*, rg.thesis, rg.status as group_status, rg.created_at
        FROM recommendation_legs rl
        JOIN recommendation_groups rg ON rl.group_id = rg.id
        WHERE rl.market_id = ? ORDER BY rg.created_at DESC LIMIT 10
        """,
        (ticker,),
        limit=0,
    )
    if legs:
        result["recommendations"] = legs

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Full market lookup")
    parser.add_argument("ticker", help="Market ticker")
    args = parser.parse_args()
    print(json.dumps(lookup(args.ticker), indent=2, default=str))

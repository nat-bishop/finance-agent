"""Category summary: market count, spreads, volume, bracket candidates.

Usage:
    python category_overview.py [CATEGORY]
"""
import argparse
import json
from db_utils import connect, materialize_latest_ids


def overview(category=None):
    """Get summary stats per category."""
    where = "WHERE e.exchange = 'kalshi'" + (
        " AND e.category = ?" if category else ""
    )
    params = (category,) if category else ()

    conn = connect()
    materialize_latest_ids(conn)

    rows = conn.execute(
        f"""
        SELECT e.category,
               COUNT(DISTINCT e.event_ticker) as events,
               COUNT(DISTINCT s.ticker) as markets,
               COUNT(DISTINCT CASE WHEN e.mutually_exclusive = 1
                   THEN e.event_ticker END) as me_events,
               AVG(s.spread_cents) as avg_spread,
               AVG(s.volume_24h) as avg_volume_24h,
               SUM(s.open_interest) as total_oi
        FROM events e
        LEFT JOIN (
            SELECT ms.* FROM market_snapshots ms
            JOIN _latest_ids li ON ms.id = li.id
        ) s ON s.event_ticker = e.event_ticker
        {where}
        GROUP BY e.category
        ORDER BY markets DESC
        """,
        params,
    ).fetchall()
    conn.close()

    return [
        {
            "category": c["category"],
            "events": c["events"],
            "markets": c["markets"],
            "mutually_exclusive_events": c["me_events"],
            "avg_spread_cents": round(c["avg_spread"], 1) if c["avg_spread"] else None,
            "avg_volume_24h": round(c["avg_volume_24h"]) if c["avg_volume_24h"] else None,
            "total_open_interest": c["total_oi"],
        }
        for c in rows
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Category overview")
    parser.add_argument("category", nargs="?", help="Specific category (omit for all)")
    args = parser.parse_args()
    for r in overview(args.category):
        print(json.dumps(r, default=str))

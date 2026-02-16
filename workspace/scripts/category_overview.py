"""Category summary: market count, spreads, volume, bracket candidates.

Usage:
    python category_overview.py [CATEGORY]
"""
import argparse
import json
from db_utils import query


def overview(category=None):
    """Get summary stats per category."""
    where = "WHERE e.exchange = 'kalshi'" + (
        " AND e.category = ?" if category else ""
    )
    params = (category,) if category else ()

    cats = query(
        f"""
        SELECT e.category,
               COUNT(DISTINCT e.event_ticker) as events,
               COUNT(DISTINCT s.ticker) as markets,
               SUM(CASE WHEN e.mutually_exclusive = 1 THEN 1 ELSE 0 END) as me_events,
               AVG(s.spread_cents) as avg_spread,
               AVG(s.volume_24h) as avg_volume_24h,
               SUM(s.open_interest) as total_oi
        FROM events e
        LEFT JOIN market_snapshots s ON s.event_ticker = e.event_ticker
            AND s.exchange = 'kalshi' AND s.status = 'open'
            AND s.id IN (
                SELECT MAX(id) FROM market_snapshots
                WHERE exchange = 'kalshi' AND status = 'open'
                GROUP BY ticker
            )
        {where}
        GROUP BY e.category
        ORDER BY markets DESC
        """,
        params,
    )

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
        for c in cats
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Category overview")
    parser.add_argument("category", nargs="?", help="Specific category (omit for all)")
    args = parser.parse_args()
    for r in overview(args.category):
        print(json.dumps(r, default=str))

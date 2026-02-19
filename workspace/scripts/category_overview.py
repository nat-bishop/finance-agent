"""Category summary: market count, spreads, volume.

Usage:
    python category_overview.py [CATEGORY]
"""
import argparse
import json
from db_utils import query


def overview(category=None):
    """Get summary stats per category using v_latest_markets view."""
    where = "WHERE category = ?" if category else ""
    params = (category,) if category else ()

    return query(
        f"""
        SELECT
            lm.category,
            COUNT(DISTINCT lm.event_ticker) as events,
            COUNT(DISTINCT lm.ticker) as markets,
            COUNT(DISTINCT CASE WHEN lm.mutually_exclusive = 1
                THEN lm.event_ticker END) as mutually_exclusive_events,
            ROUND(AVG(lm.spread_cents), 1) as avg_spread_cents,
            ROUND(AVG(lm.volume_24h)) as avg_volume_24h,
            SUM(lm.open_interest) as total_open_interest
        FROM v_latest_markets lm
        {where}
        GROUP BY lm.category
        ORDER BY markets DESC
        """,
        params,
        limit=0,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Category overview")
    parser.add_argument("category", nargs="?", help="Specific category (omit for all)")
    args = parser.parse_args()
    for r in overview(args.category):
        print(json.dumps(r, default=str))

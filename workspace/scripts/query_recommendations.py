"""Query recommendation history.

Usage:
    python query_recommendations.py                    # all pending
    python query_recommendations.py --status executed  # by status
    python query_recommendations.py --session abc123   # by session
    python query_recommendations.py --recent 10        # last N groups
"""
import argparse
import json
from collections import defaultdict
from db_utils import query


def get_recommendations(status=None, session_id=None, recent=None):
    """Query recommendation groups with their legs."""
    conditions = []
    params = []

    if status:
        conditions.append("rg.status = ?")
        params.append(status)
    if session_id:
        conditions.append("rg.session_id = ?")
        params.append(session_id)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    if recent:
        params.append(recent)
        limit = "LIMIT ?"
    else:
        limit = ""

    groups = query(
        f"""
        SELECT id, session_id, created_at, thesis, equivalence_notes,
               strategy, status, estimated_edge_pct, computed_edge_pct,
               computed_fees_usd, total_exposure_usd, expires_at,
               executed_at, reviewed_at
        FROM recommendation_groups rg
        {where}
        ORDER BY created_at DESC
        {limit}
        """,
        tuple(params),
    )

    # Batch-fetch legs for all groups
    group_ids = [g["id"] for g in groups]
    legs_by_group = defaultdict(list)
    if group_ids:
        placeholders = ",".join("?" * len(group_ids))
        all_legs = query(
            f"""
            SELECT group_id, leg_index, exchange, market_id, market_title,
                   action, side, quantity, price_cents, order_type,
                   status, order_id, is_maker, fill_price_cents,
                   fill_quantity, executed_at
            FROM recommendation_legs
            WHERE group_id IN ({placeholders})
            ORDER BY group_id, leg_index
            """,
            tuple(group_ids),
        )
        for leg in all_legs:
            legs_by_group[leg["group_id"]].append(leg)

    for group in groups:
        group["legs"] = legs_by_group.get(group["id"], [])

    return groups


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Query recommendation history")
    parser.add_argument("--status", help="Filter by status (pending/executed/rejected/partial)")
    parser.add_argument("--session", help="Filter by session ID")
    parser.add_argument("--recent", type=int, help="Show last N groups")
    args = parser.parse_args()

    if not args.status and not args.session and not args.recent:
        args.status = "pending"

    results = get_recommendations(
        status=args.status,
        session_id=args.session,
        recent=args.recent,
    )
    for r in results:
        print(json.dumps(r, indent=2, default=str))
    print(f"\n{len(results)} recommendation group(s) found")

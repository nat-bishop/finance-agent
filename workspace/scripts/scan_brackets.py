"""Scan for bracket arbitrage opportunities.

Finds mutually exclusive events where YES prices sum != 100c.

Usage:
    python scan_brackets.py [--min-edge 5] [--min-volume 100]
"""
import argparse
import json
from collections import defaultdict
from db_utils import query, latest_snapshot_ids


def scan(min_edge_cents=5, min_volume=100):
    """Find bracket arb candidates from latest market snapshots."""
    events = {
        e["event_ticker"]: e
        for e in query(
            """
            SELECT event_ticker, title, category
            FROM events
            WHERE exchange = 'kalshi' AND mutually_exclusive = 1
            """
        )
    }

    all_markets = query(
        f"""
        SELECT ticker, event_ticker, title, yes_ask, yes_bid, no_ask, no_bid,
               volume_24h, open_interest, spread_cents
        FROM market_snapshots
        WHERE exchange = 'kalshi' AND status = 'open'
          AND id IN ({latest_snapshot_ids()})
          AND event_ticker IN (
              SELECT event_ticker FROM events
              WHERE exchange = 'kalshi' AND mutually_exclusive = 1
          )
        """
    )

    by_event = defaultdict(list)
    for m in all_markets:
        by_event[m["event_ticker"]].append(m)

    results = []
    for event_ticker, markets in by_event.items():
        if len(markets) < 2:
            continue

        evt = events.get(event_ticker)
        if not evt:
            continue

        yes_prices = [m["yes_ask"] for m in markets if m["yes_ask"]]
        if len(yes_prices) == len(markets):
            yes_sum = sum(yes_prices)
            yes_edge = yes_sum - 100
            if abs(yes_edge) >= min_edge_cents:
                avg_volume = sum(m.get("volume_24h") or 0 for m in markets) / len(markets)
                if avg_volume >= min_volume:
                    results.append({
                        "event_ticker": event_ticker,
                        "event_title": evt["title"],
                        "category": evt["category"],
                        "n_markets": len(markets),
                        "yes_sum": yes_sum,
                        "yes_edge_cents": yes_edge,
                        "direction": "sell_all_yes" if yes_edge > 0 else "buy_all_yes",
                        "avg_volume_24h": round(avg_volume),
                        "markets": [
                            {
                                "ticker": m["ticker"],
                                "title": m["title"],
                                "yes_ask": m["yes_ask"],
                                "spread": m["spread_cents"],
                            }
                            for m in markets
                        ],
                    })

    return sorted(
        results,
        key=lambda r: abs(r.get("yes_edge_cents", 0)),
        reverse=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan for bracket arb opportunities")
    parser.add_argument("--min-edge", type=int, default=5, help="Min edge in cents")
    parser.add_argument("--min-volume", type=int, default=100, help="Min avg 24h volume")
    args = parser.parse_args()

    results = scan(args.min_edge, args.min_volume)
    for r in results:
        print(json.dumps(r, default=str))
    print(f"\n{len(results)} candidates found")

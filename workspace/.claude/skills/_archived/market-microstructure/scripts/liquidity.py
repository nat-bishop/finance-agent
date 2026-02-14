#!/usr/bin/env python3
"""Orderbook analysis and liquidity scoring for Kalshi markets.

Usage:
    python liquidity.py --orderbook '{"yes":[[55,100],[54,200]],"no":[[46,80],[47,120]]}' --order-size 50
"""

import argparse
import json


def analyze_orderbook(
    orderbook: dict,
    order_size: int = 10,
    daily_volume: int | None = None,
) -> dict:
    """Analyze orderbook liquidity and estimate execution costs.

    Args:
        orderbook: {"yes": [[price_cents, qty], ...], "no": [[price_cents, qty], ...]}
                   yes sorted descending (best bid first), no sorted ascending (best ask first)
        order_size: Number of contracts to estimate slippage for
        daily_volume: Optional daily volume for market impact estimation

    Returns:
        Analysis dict with spread, depth, liquidity score, slippage.
    """
    yes_levels = orderbook.get("yes", [])
    no_levels = orderbook.get("no", [])

    if not yes_levels or not no_levels:
        return {"error": "Orderbook has no levels on one or both sides"}

    # Sort: yes descending by price, no ascending by price
    yes_sorted = sorted(yes_levels, key=lambda x: x[0], reverse=True)
    no_sorted = sorted(no_levels, key=lambda x: x[0])

    best_bid = yes_sorted[0][0]  # highest yes bid
    best_ask = 100 - no_sorted[0][0]  # convert no price to yes equivalent

    # In Kalshi, yes price + no price = 100 cents
    # So best ask for YES = 100 - best_no_bid
    spread = best_ask - best_bid
    mid_price = (best_bid + best_ask) / 2
    relative_spread = spread / mid_price * 100 if mid_price > 0 else float("inf")

    # Depth analysis
    yes_depth = sum(qty for _, qty in yes_sorted[:3])
    no_depth = sum(qty for _, qty in no_sorted[:3])
    total_depth_top3 = yes_depth + no_depth

    yes_total_depth = sum(qty for _, qty in yes_sorted)
    no_total_depth = sum(qty for _, qty in no_sorted)

    # Slippage for buying YES (walking up the ask side = walking down no bids)
    def estimate_slippage(levels: list, size: int, is_buy_yes: bool) -> dict:
        remaining = size
        total_cost = 0
        fills = []

        for price, qty in levels:
            fill_qty = min(remaining, qty)
            if is_buy_yes:
                fill_price = 100 - price  # convert no price to yes cost
            else:
                fill_price = price

            total_cost += fill_qty * fill_price
            fills.append({"price": fill_price, "qty": fill_qty})
            remaining -= fill_qty
            if remaining <= 0:
                break

        filled = size - remaining
        if filled == 0:
            return {"filled": 0, "avg_price": 0, "slippage_cents": 0}

        avg_price = total_cost / filled
        slippage = avg_price - (best_ask if is_buy_yes else best_bid)

        return {
            "filled": filled,
            "unfilled": remaining,
            "avg_price_cents": round(avg_price, 2),
            "slippage_cents": round(slippage, 2),
            "slippage_pct": round(slippage / mid_price * 100, 2) if mid_price > 0 else 0,
            "total_cost_cents": round(total_cost, 0),
            "fills": fills,
        }

    buy_yes_slippage = estimate_slippage(no_sorted, order_size, is_buy_yes=True)
    sell_yes_slippage = estimate_slippage(yes_sorted, order_size, is_buy_yes=False)

    # Liquidity score (0-100)
    spread_score = max(0, 100 - spread * 10)  # 0 spread = 100, 10+ spread = 0
    depth_score = min(100, total_depth_top3 / 5)  # 500+ contracts = 100
    volume_score = min(100, (daily_volume or 0) / 100)  # 10000+ = 100

    liquidity_score = 0.4 * spread_score + 0.3 * depth_score + 0.3 * volume_score

    # Market impact estimate
    impact = None
    if daily_volume and daily_volume > 0:
        k = 0.3  # market impact coefficient
        impact_cents = spread / 2 + k * (order_size / daily_volume) ** 0.5 * mid_price
        impact = {
            "estimated_impact_cents": round(impact_cents, 2),
            "impact_pct_of_mid": round(impact_cents / mid_price * 100, 2) if mid_price > 0 else 0,
        }

    return {
        "spread": {
            "bid": best_bid,
            "ask": best_ask,
            "spread_cents": spread,
            "mid_price_cents": round(mid_price, 1),
            "relative_spread_pct": round(relative_spread, 2),
        },
        "depth": {
            "yes_top3": yes_depth,
            "no_top3": no_depth,
            "yes_total": yes_total_depth,
            "no_total": no_total_depth,
            "yes_levels": len(yes_sorted),
            "no_levels": len(no_sorted),
        },
        "liquidity_score": round(liquidity_score, 1),
        "slippage_buy_yes": buy_yes_slippage,
        "slippage_sell_yes": sell_yes_slippage,
        "market_impact": impact,
        "recommendation": (
            "Liquid — market orders OK"
            if liquidity_score > 70
            else "Moderate — prefer limit orders"
            if liquidity_score > 40
            else "Illiquid — limit orders only, consider smaller size"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Orderbook liquidity analysis")
    parser.add_argument("--orderbook", type=str, required=True, help="Orderbook JSON")
    parser.add_argument("--order-size", type=int, default=10, help="Order size in contracts")
    parser.add_argument("--daily-volume", type=int, default=None, help="Daily trading volume")

    args = parser.parse_args()
    orderbook = json.loads(args.orderbook)

    result = analyze_orderbook(
        orderbook=orderbook,
        order_size=args.order_size,
        daily_volume=args.daily_volume,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

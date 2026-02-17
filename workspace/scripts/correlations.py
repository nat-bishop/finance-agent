"""Compute pairwise price correlations within a category.

Uses kalshi_daily + kalshi_market_meta for historical data.

Usage:
    python correlations.py "Politics" [--min-days 30] [--min-corr 0.5]
"""
import argparse
import json
import math
from collections import defaultdict
from db_utils import query


def pearson(x, y):
    """Compute Pearson correlation coefficient."""
    n = len(x)
    if n < 5:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / n)
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / n)
    if sx == 0 or sy == 0:
        return None
    return sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / (n * sx * sy)


def get_correlations(category, min_days=30, min_corr=0.5, max_tickers=200):
    """Find correlated market pairs within a category.

    Limits to top max_tickers by data points to keep O(N^2) tractable.
    """
    tickers = query(
        """
        SELECT m.ticker, m.title, COUNT(d.id) as days
        FROM kalshi_market_meta m
        JOIN kalshi_daily d ON m.ticker = d.ticker_name
        WHERE m.category = ?
        GROUP BY m.ticker
        HAVING days >= ?
        ORDER BY days DESC
        LIMIT ?
        """,
        (category, min_days, max_tickers),
    )

    if not tickers:
        return []

    ticker_names = [t["ticker"] for t in tickers]
    placeholders = ",".join("?" * len(ticker_names))
    all_daily = query(
        f"""
        SELECT ticker_name, date, (high + low) / 2 as mid
        FROM kalshi_daily
        WHERE ticker_name IN ({placeholders})
          AND high IS NOT NULL AND low IS NOT NULL
        ORDER BY ticker_name, date
        """,
        tuple(ticker_names),
    )

    series = defaultdict(dict)
    for r in all_daily:
        series[r["ticker_name"]][r["date"]] = r["mid"]

    results = []
    ticker_list = list(series.keys())
    for i in range(len(ticker_list)):
        for j in range(i + 1, len(ticker_list)):
            t1, t2 = ticker_list[i], ticker_list[j]
            common_dates = sorted(set(series[t1].keys()) & set(series[t2].keys()))
            if len(common_dates) < min_days:
                continue
            x = [series[t1][d] for d in common_dates]
            y = [series[t2][d] for d in common_dates]
            corr = pearson(x, y)
            if corr is not None and abs(corr) >= min_corr:
                t1_info = next(t for t in tickers if t["ticker"] == t1)
                t2_info = next(t for t in tickers if t["ticker"] == t2)
                results.append({
                    "ticker_1": t1,
                    "title_1": t1_info["title"],
                    "ticker_2": t2,
                    "title_2": t2_info["title"],
                    "correlation": round(corr, 3),
                    "common_days": len(common_dates),
                    "direction": "positive" if corr > 0 else "negative",
                })

    return sorted(results, key=lambda r: abs(r["correlation"]), reverse=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find correlated market pairs")
    parser.add_argument("category", help="Market category to analyze")
    parser.add_argument("--min-days", type=int, default=30, help="Min overlapping days")
    parser.add_argument("--min-corr", type=float, default=0.5, help="Min absolute correlation")
    parser.add_argument("--max-tickers", type=int, default=200, help="Max tickers to compare")
    args = parser.parse_args()

    results = get_correlations(args.category, args.min_days, args.min_corr, args.max_tickers)
    for r in results:
        print(json.dumps(r))
    print(f"\n{len(results)} correlated pairs found")

"""Compute pairwise price correlations within a category using DuckDB CORR().

Uses v_daily_with_meta view for historical data with titles.

Usage:
    python correlations.py "Politics" [--min-days 30] [--min-corr 0.5] [--max-tickers 200]
"""
import argparse
import json
from db_utils import query


def get_correlations(category, min_days=30, min_corr=0.5, max_tickers=200):
    """Find correlated market pairs within a category.

    Uses DuckDB's built-in CORR() aggregate for efficient computation.
    Limits to top max_tickers by data points to keep O(N^2) tractable.
    """
    results = query(
        """
        WITH eligible AS (
            SELECT ticker_name, title,
                   COUNT(*) as days,
                   MIN(date) as first_date,
                   MAX(date) as last_date
            FROM v_daily_with_meta
            WHERE category = ?
              AND high IS NOT NULL AND low IS NOT NULL
            GROUP BY ticker_name, title
            HAVING COUNT(*) >= ?
            ORDER BY COUNT(*) DESC
            LIMIT ?
        ),
        daily_mid AS (
            SELECT d.ticker_name, d.date, (d.high + d.low) / 2 as mid
            FROM v_daily_with_meta d
            JOIN eligible e ON d.ticker_name = e.ticker_name
            WHERE d.high IS NOT NULL AND d.low IS NOT NULL
        )
        SELECT
            a.ticker_name as ticker_1,
            e1.title as title_1,
            b.ticker_name as ticker_2,
            e2.title as title_2,
            ROUND(CORR(a.mid, b.mid), 3) as correlation,
            COUNT(*) as common_days,
            CASE WHEN CORR(a.mid, b.mid) > 0 THEN 'positive' ELSE 'negative' END as direction
        FROM daily_mid a
        JOIN daily_mid b ON a.date = b.date AND a.ticker_name < b.ticker_name
        JOIN eligible e1 ON a.ticker_name = e1.ticker_name
        JOIN eligible e2 ON b.ticker_name = e2.ticker_name
        GROUP BY a.ticker_name, e1.title, b.ticker_name, e2.title
        HAVING COUNT(*) >= ? AND ABS(CORR(a.mid, b.mid)) >= ?
        ORDER BY ABS(CORR(a.mid, b.mid)) DESC
        """,
        (category, min_days, max_tickers, min_days, min_corr),
        limit=0,
    )
    return results


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

#!/usr/bin/env python3
"""Monte Carlo portfolio simulation for prediction market positions.

Usage:
    python simulate.py --positions '[{"ticker":"A","prob":0.6,"size":10,"cost_per":0.45}]' --n-trials 10000
    python simulate.py --positions-file data/positions.json --n-trials 50000
"""

import argparse
import json
import sys

import numpy as np
from scipy import stats


def simulate_portfolio(
    positions: list[dict],
    n_trials: int = 10000,
    correlation_matrix: np.ndarray | None = None,
    seed: int | None = None,
) -> dict:
    """Run Monte Carlo simulation on a portfolio of binary positions.

    Args:
        positions: List of dicts with keys: ticker, prob, size, cost_per
        n_trials: Number of simulation trials
        correlation_matrix: Optional NxN correlation matrix for copula
        seed: Random seed for reproducibility

    Returns:
        Dict with summary statistics and histogram data.
    """
    rng = np.random.default_rng(seed)
    n_pos = len(positions)

    probs = np.array([p["prob"] for p in positions])
    sizes = np.array([p["size"] for p in positions])
    costs = np.array([p["cost_per"] for p in positions])
    payouts = np.ones(n_pos)  # $1 per contract if correct

    # Generate outcomes
    if correlation_matrix is not None:
        corr = np.array(correlation_matrix)
        # Gaussian copula: generate correlated normals, transform to uniform
        L = np.linalg.cholesky(corr)
        z = rng.standard_normal((n_trials, n_pos))
        correlated_normals = z @ L.T
        uniforms = stats.norm.cdf(correlated_normals)
    else:
        uniforms = rng.uniform(size=(n_trials, n_pos))

    # Binary outcomes: 1 if uniform < prob
    outcomes = (uniforms < probs).astype(float)

    # P&L per position per trial
    # Win: size * (payout - cost), Lose: size * (-cost)
    pnl_per_position = outcomes * sizes * (payouts - costs) + (1 - outcomes) * sizes * (-costs)
    portfolio_pnl = pnl_per_position.sum(axis=1)

    # Statistics
    total_cost = float((sizes * costs).sum())
    mean_pnl = float(portfolio_pnl.mean())
    median_pnl = float(np.median(portfolio_pnl))
    std_pnl = float(portfolio_pnl.std())
    min_pnl = float(portfolio_pnl.min())
    max_pnl = float(portfolio_pnl.max())

    # VaR and CVaR at 95%
    var_95 = float(np.percentile(portfolio_pnl, 5))  # 5th percentile = 95% VaR
    cvar_95 = (
        float(portfolio_pnl[portfolio_pnl <= var_95].mean())
        if (portfolio_pnl <= var_95).any()
        else var_95
    )

    win_rate = float((portfolio_pnl > 0).mean())
    sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0.0
    skewness = float(stats.skew(portfolio_pnl))
    kurtosis = float(stats.kurtosis(portfolio_pnl))

    # Histogram data (20 bins)
    hist_counts, hist_edges = np.histogram(portfolio_pnl, bins=20)

    return {
        "summary": {
            "n_positions": n_pos,
            "n_trials": n_trials,
            "total_cost_usd": round(total_cost, 2),
            "expected_pnl": round(mean_pnl, 2),
            "median_pnl": round(median_pnl, 2),
            "std_pnl": round(std_pnl, 2),
            "var_95_pct": round(var_95, 2),
            "cvar_95_pct": round(cvar_95, 2),
            "max_loss": round(min_pnl, 2),
            "max_gain": round(max_pnl, 2),
            "win_rate": round(win_rate, 4),
            "sharpe_analogue": round(sharpe, 4),
            "skewness": round(skewness, 4),
            "kurtosis": round(kurtosis, 4),
        },
        "percentiles": {
            "1st": round(float(np.percentile(portfolio_pnl, 1)), 2),
            "5th": round(float(np.percentile(portfolio_pnl, 5)), 2),
            "10th": round(float(np.percentile(portfolio_pnl, 10)), 2),
            "25th": round(float(np.percentile(portfolio_pnl, 25)), 2),
            "50th": round(float(np.percentile(portfolio_pnl, 50)), 2),
            "75th": round(float(np.percentile(portfolio_pnl, 75)), 2),
            "90th": round(float(np.percentile(portfolio_pnl, 90)), 2),
            "95th": round(float(np.percentile(portfolio_pnl, 95)), 2),
            "99th": round(float(np.percentile(portfolio_pnl, 99)), 2),
        },
        "histogram": {
            "counts": hist_counts.tolist(),
            "bin_edges": [round(e, 2) for e in hist_edges.tolist()],
        },
        "per_position": [
            {
                "ticker": positions[i]["ticker"],
                "expected_pnl": round(float(pnl_per_position[:, i].mean()), 2),
                "std_pnl": round(float(pnl_per_position[:, i].std()), 2),
                "win_rate": round(float(outcomes[:, i].mean()), 4),
            }
            for i in range(n_pos)
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo portfolio simulation")
    parser.add_argument("--positions", type=str, help="JSON array of positions")
    parser.add_argument("--positions-file", type=str, help="Path to positions JSON file")
    parser.add_argument("--n-trials", type=int, default=10000, help="Number of trials")
    parser.add_argument(
        "--correlation-matrix", type=str, default=None, help="JSON correlation matrix"
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed")

    args = parser.parse_args()

    if args.positions_file:
        with open(args.positions_file) as f:
            positions = json.load(f)
    elif args.positions:
        positions = json.loads(args.positions)
    else:
        print(json.dumps({"error": "Provide --positions or --positions-file"}))
        sys.exit(1)

    corr = None
    if args.correlation_matrix:
        corr = json.loads(args.correlation_matrix)

    result = simulate_portfolio(
        positions=positions,
        n_trials=args.n_trials,
        correlation_matrix=corr,
        seed=args.seed,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

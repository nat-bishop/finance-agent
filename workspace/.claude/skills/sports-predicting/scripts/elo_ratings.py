#!/usr/bin/env python3
"""Elo rating system for sports prediction markets.

Usage:
    python elo_ratings.py --games-file data/nba_games.csv --predict "Lakers vs Celtics" --home-advantage 80
    python elo_ratings.py --games-file data/nfl_games.csv --k-factor 20

Games CSV format:
    date,home_team,away_team,home_score,away_score
"""

import argparse
import json
import sys
from collections import defaultdict

import numpy as np
import pandas as pd


def expected_score(rating_a: float, rating_b: float) -> float:
    """Compute expected score for player A given ratings."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def compute_elo_ratings(
    games: pd.DataFrame,
    k_factor: float = 20.0,
    initial_rating: float = 1500.0,
    home_advantage: float = 0.0,
) -> dict:
    """Compute Elo ratings from game history.

    Args:
        games: DataFrame with columns: date, home_team, away_team, home_score, away_score
        k_factor: K-factor for rating updates
        initial_rating: Starting rating for new teams
        home_advantage: Elo bonus for home team

    Returns:
        Dict with current ratings, history, and accuracy metrics.
    """
    required = ["home_team", "away_team", "home_score", "away_score"]
    missing = [c for c in required if c not in games.columns]
    if missing:
        return {"error": f"Missing columns: {missing}"}

    ratings: dict[str, float] = defaultdict(lambda: initial_rating)
    history: list[dict] = []
    correct_predictions = 0
    total_games = 0
    brier_sum = 0.0

    for _, row in games.iterrows():
        home = str(row["home_team"])
        away = str(row["away_team"])
        home_score = float(row["home_score"])
        away_score = float(row["away_score"])

        # Adjusted ratings
        home_elo = ratings[home] + home_advantage
        away_elo = ratings[away]

        # Expected scores
        exp_home = expected_score(home_elo, away_elo)
        exp_away = 1 - exp_home

        # Actual outcome
        if home_score > away_score:
            actual_home = 1.0
        elif home_score < away_score:
            actual_home = 0.0
        else:
            actual_home = 0.5

        actual_away = 1 - actual_home

        # Track accuracy
        total_games += 1
        predicted_home_win = exp_home > 0.5
        actual_home_win = actual_home > 0.5
        if predicted_home_win == actual_home_win or actual_home == 0.5:
            correct_predictions += 1
        brier_sum += (exp_home - actual_home) ** 2

        # Update ratings
        new_home = ratings[home] + k_factor * (actual_home - exp_home)
        new_away = ratings[away] + k_factor * (actual_away - exp_away)

        history.append({
            "home": home,
            "away": away,
            "home_score": home_score,
            "away_score": away_score,
            "home_win_prob": round(exp_home, 4),
            "home_elo_before": round(ratings[home], 1),
            "away_elo_before": round(ratings[away], 1),
            "home_elo_after": round(new_home, 1),
            "away_elo_after": round(new_away, 1),
        })

        ratings[home] = new_home
        ratings[away] = new_away

    # Sort ratings
    sorted_ratings = sorted(
        [(team, round(rating, 1)) for team, rating in ratings.items()],
        key=lambda x: x[1],
        reverse=True,
    )

    accuracy = correct_predictions / total_games if total_games > 0 else 0
    brier = brier_sum / total_games if total_games > 0 else 0

    return {
        "ratings": [{"team": t, "elo": r} for t, r in sorted_ratings],
        "n_teams": len(ratings),
        "n_games": total_games,
        "k_factor": k_factor,
        "home_advantage": home_advantage,
        "accuracy": {
            "correct_predictions": correct_predictions,
            "total_games": total_games,
            "accuracy_pct": round(accuracy * 100, 2),
            "brier_score": round(brier, 6),
        },
        "recent_games": history[-10:] if len(history) > 10 else history,
    }


def predict_matchup(
    ratings: dict,
    home_team: str,
    away_team: str,
    home_advantage: float = 0.0,
) -> dict:
    """Predict outcome of a specific matchup.

    Args:
        ratings: Current Elo ratings dict (team -> rating)
        home_team: Home team name
        away_team: Away team name
        home_advantage: Elo bonus for home team

    Returns:
        Prediction dict.
    """
    home_elo = ratings.get(home_team, 1500.0) + home_advantage
    away_elo = ratings.get(away_team, 1500.0)

    win_prob_home = expected_score(home_elo, away_elo)

    elo_diff = home_elo - away_elo

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_elo": round(ratings.get(home_team, 1500.0), 1),
        "away_elo": round(ratings.get(away_team, 1500.0), 1),
        "home_elo_adjusted": round(home_elo, 1),
        "elo_difference": round(elo_diff, 1),
        "home_win_probability": round(win_prob_home, 4),
        "away_win_probability": round(1 - win_prob_home, 4),
        "implied_spread": round(elo_diff / 25, 1),  # rough points conversion
    }


def main():
    parser = argparse.ArgumentParser(description="Elo rating system for sports")
    parser.add_argument("--games-file", type=str, required=True, help="CSV of game results")
    parser.add_argument("--k-factor", type=float, default=20.0, help="K-factor")
    parser.add_argument("--home-advantage", type=float, default=0.0, help="Home advantage in Elo")
    parser.add_argument("--predict", type=str, default=None, help="Predict matchup: 'TeamA vs TeamB'")

    args = parser.parse_args()

    try:
        games = pd.read_csv(args.games_file)
    except FileNotFoundError:
        print(json.dumps({"error": f"File not found: {args.games_file}"}))
        sys.exit(1)

    result = compute_elo_ratings(
        games,
        k_factor=args.k_factor,
        home_advantage=args.home_advantage,
    )

    if "error" in result:
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Add matchup prediction if requested
    if args.predict:
        parts = args.predict.split(" vs ")
        if len(parts) == 2:
            ratings_dict = {r["team"]: r["elo"] for r in result["ratings"]}
            prediction = predict_matchup(
                ratings_dict,
                home_team=parts[0].strip(),
                away_team=parts[1].strip(),
                home_advantage=args.home_advantage,
            )
            result["matchup_prediction"] = prediction
        else:
            result["prediction_error"] = "Use format: 'TeamA vs TeamB'"

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

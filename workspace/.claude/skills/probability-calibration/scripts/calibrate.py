#!/usr/bin/env python3
"""Probability calibration analysis for prediction tracking.

Usage:
    python calibrate.py --predictions-file data/predictions.csv
    python calibrate.py --predictions-file data/predictions.csv --n-bins 10
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd


def compute_calibration(predictions: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> dict:
    """Compute calibration metrics and curve data.

    Args:
        predictions: Array of predicted probabilities (0-1)
        outcomes: Array of binary outcomes (0 or 1)
        n_bins: Number of calibration bins

    Returns:
        Dict with Brier score, log loss, calibration curve, and diagnosis.
    """
    n = len(predictions)
    if n == 0:
        return {"error": "No predictions to evaluate"}

    # Brier Score
    brier = float(np.mean((predictions - outcomes) ** 2))

    # Log Loss (with clipping to avoid log(0))
    eps = 1e-15
    clipped = np.clip(predictions, eps, 1 - eps)
    log_loss = -float(np.mean(outcomes * np.log(clipped) + (1 - outcomes) * np.log(1 - clipped)))

    # Calibration curve
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_centers = []
    bin_actual = []
    bin_counts = []

    for i in range(n_bins):
        mask = (predictions >= bin_edges[i]) & (predictions < bin_edges[i + 1])
        if i == n_bins - 1:  # include right edge in last bin
            mask = (predictions >= bin_edges[i]) & (predictions <= bin_edges[i + 1])
        count = mask.sum()
        if count > 0:
            bin_centers.append(round(float((bin_edges[i] + bin_edges[i + 1]) / 2), 3))
            bin_actual.append(round(float(outcomes[mask].mean()), 4))
            bin_counts.append(int(count))

    # Reliability diagram deviation (mean absolute calibration error)
    if bin_centers:
        mace = float(np.mean([abs(c - a) for c, a in zip(bin_centers, bin_actual, strict=False)]))
    else:
        mace = 0.0

    # Diagnosis
    diagnosis = []
    if brier > 0.25:
        diagnosis.append(
            "Brier score worse than naive 50% baseline — predictions have negative value"
        )
    elif brier > 0.20:
        diagnosis.append("Brier score marginal — slight improvement over baseline")
    elif brier > 0.15:
        diagnosis.append("Brier score decent — room for improvement")
    elif brier > 0.10:
        diagnosis.append("Brier score good — solid calibration")
    else:
        diagnosis.append("Brier score excellent")

    # Check for overconfidence/underconfidence
    if len(bin_centers) >= 3:
        deviations = [a - c for c, a in zip(bin_centers, bin_actual, strict=False)]
        avg_deviation = np.mean(deviations)
        if avg_deviation > 0.05:
            diagnosis.append("Underconfident: actual outcomes consistently better than predicted")
        elif avg_deviation < -0.05:
            diagnosis.append("Overconfident: actual outcomes consistently worse than predicted")
        else:
            diagnosis.append("No systematic over/under-confidence detected")

    # Check high-confidence accuracy
    high_conf_mask = (predictions > 0.8) | (predictions < 0.2)
    if high_conf_mask.sum() >= 5:
        high_conf_brier = float(
            np.mean((predictions[high_conf_mask] - outcomes[high_conf_mask]) ** 2)
        )
        if high_conf_brier > brier * 1.5:
            diagnosis.append("High-confidence predictions are disproportionately inaccurate")

    return {
        "n_predictions": n,
        "brier_score": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "mean_abs_calibration_error": round(mace, 6),
        "overall_accuracy": round(float(((predictions >= 0.5).astype(int) == outcomes).mean()), 4),
        "mean_prediction": round(float(predictions.mean()), 4),
        "base_rate": round(float(outcomes.mean()), 4),
        "calibration_curve": {
            "bin_centers": bin_centers,
            "actual_frequencies": bin_actual,
            "bin_counts": bin_counts,
        },
        "diagnosis": diagnosis,
    }


def main():
    parser = argparse.ArgumentParser(description="Probability calibration analysis")
    parser.add_argument("--predictions-file", type=str, required=True, help="CSV with predictions")
    parser.add_argument("--n-bins", type=int, default=10, help="Number of calibration bins")

    args = parser.parse_args()

    try:
        df = pd.read_csv(args.predictions_file)
    except FileNotFoundError:
        print(json.dumps({"error": f"File not found: {args.predictions_file}"}))
        sys.exit(1)

    # Filter to resolved predictions only
    required = ["prediction", "outcome"]
    for col in required:
        if col not in df.columns:
            print(json.dumps({"error": f"Missing column: {col}"}))
            sys.exit(1)

    resolved = df.dropna(subset=["outcome"])
    if len(resolved) == 0:
        print(json.dumps({"error": "No resolved predictions found"}))
        sys.exit(1)

    predictions = resolved["prediction"].values.astype(float)
    outcomes = resolved["outcome"].values.astype(float)

    result = compute_calibration(predictions, outcomes, n_bins=args.n_bins)

    # Add per-category breakdown if 'confidence' column exists
    if "confidence" in resolved.columns:
        categories = {}
        for conf in resolved["confidence"].dropna().unique():
            mask = resolved["confidence"] == conf
            if mask.sum() >= 3:
                cat_result = compute_calibration(
                    predictions[mask], outcomes[mask], n_bins=min(5, args.n_bins)
                )
                categories[str(conf)] = {
                    "n": int(mask.sum()),
                    "brier_score": cat_result["brier_score"],
                    "accuracy": cat_result["overall_accuracy"],
                }
        if categories:
            result["by_confidence"] = categories

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

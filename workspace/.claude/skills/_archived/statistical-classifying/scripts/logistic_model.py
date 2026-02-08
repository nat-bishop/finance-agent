#!/usr/bin/env python3
"""Logistic regression for binary outcome prediction in markets.

Usage:
    python logistic_model.py --data-file data/features.csv --target outcome --features "base_rate,volume,spread"
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import StandardScaler


def train_logistic(
    df: pd.DataFrame,
    target: str,
    features: list[str],
    test_size: float = 0.2,
    seed: int = 42,
) -> dict:
    """Train logistic regression and return analysis.

    Args:
        df: DataFrame with features and target
        target: Target column name (binary 0/1)
        features: List of feature column names
        test_size: Fraction for test set
        seed: Random seed

    Returns:
        Model analysis dict.
    """
    # Validate
    missing = [f for f in features + [target] if f not in df.columns]
    if missing:
        return {"error": f"Missing columns: {missing}"}

    df_clean = df[features + [target]].dropna()
    if len(df_clean) < 20:
        return {"error": f"Insufficient data: {len(df_clean)} rows (need 20+)"}

    X = df_clean[features].values
    y = df_clean[target].values.astype(int)

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=test_size, random_state=seed, stratify=y
    )

    # Fit model
    model = LogisticRegression(C=1.0, penalty="l2", solver="lbfgs", max_iter=1000)
    model.fit(X_train, y_train)

    # Predictions
    y_pred_train = model.predict(X_train)
    y_prob_train = model.predict_proba(X_train)[:, 1]
    y_pred_test = model.predict(X_test)
    y_prob_test = model.predict_proba(X_test)[:, 1]

    # Cross-validation
    cv_scores = cross_val_score(
        model, X_scaled, y, cv=min(5, len(df_clean) // 5), scoring="accuracy"
    )

    # Coefficients and odds ratios
    coefficients = []
    for i, feat in enumerate(features):
        coef = float(model.coef_[0][i])
        odds_ratio = float(np.exp(coef))
        coefficients.append(
            {
                "feature": feat,
                "coefficient": round(coef, 4),
                "odds_ratio": round(odds_ratio, 4),
                "direction": "positive" if coef > 0 else "negative",
                "feature_mean": round(float(df_clean[feat].mean()), 4),
                "feature_std": round(float(df_clean[feat].std()), 4),
            }
        )

    # Sort by absolute importance
    coefficients.sort(key=lambda x: abs(x["coefficient"]), reverse=True)

    # Metrics
    train_metrics = {
        "accuracy": round(float(accuracy_score(y_train, y_pred_train)), 4),
        "auc_roc": round(float(roc_auc_score(y_train, y_prob_train)), 4),
        "log_loss": round(float(log_loss(y_train, y_prob_train)), 4),
        "brier_score": round(float(brier_score_loss(y_train, y_prob_train)), 4),
    }

    test_metrics = {
        "accuracy": round(float(accuracy_score(y_test, y_pred_test)), 4),
        "auc_roc": round(float(roc_auc_score(y_test, y_prob_test)), 4),
        "log_loss": round(float(log_loss(y_test, y_prob_test)), 4),
        "brier_score": round(float(brier_score_loss(y_test, y_prob_test)), 4),
    }

    return {
        "n_train": len(y_train),
        "n_test": len(y_test),
        "base_rate": round(float(y.mean()), 4),
        "intercept": round(float(model.intercept_[0]), 4),
        "coefficients": coefficients,
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "cross_validation": {
            "mean_accuracy": round(float(cv_scores.mean()), 4),
            "std_accuracy": round(float(cv_scores.std()), 4),
            "folds": len(cv_scores),
        },
        "predictions_sample": [
            {"prob": round(float(p), 4), "actual": int(a)}
            for p, a in zip(y_prob_test[:10], y_test[:10], strict=False)
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Logistic regression for binary prediction")
    parser.add_argument("--data-file", type=str, required=True, help="CSV file path")
    parser.add_argument("--target", type=str, required=True, help="Target column (binary)")
    parser.add_argument(
        "--features", type=str, required=True, help="Comma-separated feature names"
    )
    parser.add_argument("--test-size", type=float, default=0.2, help="Test set fraction")

    args = parser.parse_args()

    try:
        df = pd.read_csv(args.data_file)
    except FileNotFoundError:
        print(json.dumps({"error": f"File not found: {args.data_file}"}))
        sys.exit(1)

    features = [f.strip() for f in args.features.split(",")]
    result = train_logistic(df, target=args.target, features=features, test_size=args.test_size)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

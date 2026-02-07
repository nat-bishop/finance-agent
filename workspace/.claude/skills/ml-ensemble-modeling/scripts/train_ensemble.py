#!/usr/bin/env python3
"""Ensemble model training (Random Forest / XGBoost) for prediction markets.

Usage:
    python train_ensemble.py --data-file data/features.csv --target outcome --features "f1,f2,f3" --model random_forest
    python train_ensemble.py --data-file data/features.csv --target outcome --features "f1,f2,f3" --model xgboost
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score, log_loss, brier_score_loss
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.preprocessing import StandardScaler


def train_ensemble(
    df: pd.DataFrame,
    target: str,
    features: list[str],
    model_type: str = "random_forest",
    test_size: float = 0.2,
    seed: int = 42,
) -> dict:
    """Train an ensemble model and return analysis.

    Args:
        df: DataFrame with features and target
        target: Target column name (binary 0/1)
        features: Feature column names
        model_type: "random_forest" or "xgboost"
        test_size: Test fraction
        seed: Random seed

    Returns:
        Model analysis dict.
    """
    missing = [f for f in features + [target] if f not in df.columns]
    if missing:
        return {"error": f"Missing columns: {missing}"}

    df_clean = df[features + [target]].dropna()
    if len(df_clean) < 30:
        return {"error": f"Insufficient data: {len(df_clean)} rows (need 30+)"}

    X = df_clean[features].values
    y = df_clean[target].values.astype(int)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=test_size, random_state=seed, stratify=y
    )

    # Build model
    if model_type == "random_forest":
        model = RandomForestClassifier(
            n_estimators=500,
            max_depth=10,
            min_samples_leaf=5,
            random_state=seed,
            n_jobs=-1,
        )
    elif model_type == "xgboost":
        # Use sklearn's GradientBoosting as portable XGBoost alternative
        model = GradientBoostingClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            min_samples_leaf=5,
            random_state=seed,
        )
    else:
        return {"error": f"Unknown model type: {model_type}"}

    model.fit(X_train, y_train)

    # Predictions
    y_prob_train = model.predict_proba(X_train)[:, 1]
    y_pred_test = model.predict(X_test)
    y_prob_test = model.predict_proba(X_test)[:, 1]

    # Feature importance
    importances = model.feature_importances_
    feature_importance = sorted(
        [
            {"feature": feat, "importance": round(float(imp), 4)}
            for feat, imp in zip(features, importances)
        ],
        key=lambda x: x["importance"],
        reverse=True,
    )

    # Cross-validation
    cv = StratifiedKFold(n_splits=min(5, len(df_clean) // 10), shuffle=True, random_state=seed)
    cv_scores = cross_val_score(model, X_scaled, y, cv=cv, scoring="accuracy")
    cv_auc = cross_val_score(model, X_scaled, y, cv=cv, scoring="roc_auc")

    # Metrics
    train_metrics = {
        "accuracy": round(float(accuracy_score(y_train, (y_prob_train > 0.5).astype(int))), 4),
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

    # Overfitting check
    overfit_gap = train_metrics["accuracy"] - test_metrics["accuracy"]
    overfit_warning = None
    if overfit_gap > 0.10:
        overfit_warning = f"Significant overfitting detected (train-test gap: {overfit_gap:.2f})"
    elif overfit_gap > 0.05:
        overfit_warning = f"Mild overfitting (train-test gap: {overfit_gap:.2f})"

    return {
        "model_type": model_type,
        "n_train": len(y_train),
        "n_test": len(y_test),
        "base_rate": round(float(y.mean()), 4),
        "feature_importance": feature_importance,
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "cross_validation": {
            "mean_accuracy": round(float(cv_scores.mean()), 4),
            "std_accuracy": round(float(cv_scores.std()), 4),
            "mean_auc": round(float(cv_auc.mean()), 4),
            "std_auc": round(float(cv_auc.std()), 4),
        },
        "overfit_warning": overfit_warning,
        "predictions_sample": [
            {"prob": round(float(p), 4), "actual": int(a)}
            for p, a in zip(y_prob_test[:10], y_test[:10])
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Ensemble model training")
    parser.add_argument("--data-file", type=str, required=True, help="CSV file path")
    parser.add_argument("--target", type=str, required=True, help="Target column (binary)")
    parser.add_argument("--features", type=str, required=True, help="Comma-separated feature names")
    parser.add_argument("--model", type=str, default="random_forest",
                        choices=["random_forest", "xgboost"], help="Model type")
    parser.add_argument("--test-size", type=float, default=0.2, help="Test set fraction")

    args = parser.parse_args()

    try:
        df = pd.read_csv(args.data_file)
    except FileNotFoundError:
        print(json.dumps({"error": f"File not found: {args.data_file}"}))
        sys.exit(1)

    features = [f.strip() for f in args.features.split(",")]
    result = train_ensemble(
        df, target=args.target, features=features,
        model_type=args.model, test_size=args.test_size,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

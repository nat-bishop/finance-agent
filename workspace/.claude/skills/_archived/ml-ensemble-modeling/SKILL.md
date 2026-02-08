# ML Ensemble Modeling

The agent uses this skill when building complex predictive models with many features or non-linear relationships. Trigger phrases: "random forest", "XGBoost", "ensemble", "machine learning", "feature engineering", "cross-validation", "complex prediction".

## Overview

Ensemble methods combine multiple models for robust predictions. Use when:
- Large dataset (1000+ observations)
- Many features (10+)
- Non-linear relationships between features and outcome
- Need better accuracy than logistic regression

## Models

### Random Forest
- Ensemble of decision trees with bagging
- Handles non-linear features naturally
- Built-in feature importance
- Resistant to overfitting with enough trees
- Good default: 500 trees, max_depth=10

### XGBoost (Gradient Boosted Trees)
- Sequential boosting of weak learners
- State-of-the-art for tabular data
- Requires more tuning than RF
- Key hyperparameters: learning_rate, max_depth, n_estimators, subsample

### LSTM (Long Short-Term Memory)
- Neural network for sequential data
- Captures long-range temporal dependencies
- Use for: time-dependent prediction markets, sequential data
- Requires more data (5000+ observations) and compute
- Agent should write custom scripts in `analysis/` for LSTM

## Feature Engineering

### General Principles
1. **Lag features**: Past N values of key variables
2. **Rolling statistics**: Mean, std, min, max over windows
3. **Interaction features**: Products/ratios of related features
4. **Time features**: Day of week, month, days to settlement
5. **Categorical encoding**: One-hot for categories, target encoding for high cardinality

### Prediction Market Features
- Market price history (lags 1, 3, 7, 14 days)
- Volume profile (rolling 7-day, 30-day)
- Spread history
- Related market prices
- External data (economic indicators, polls, weather forecasts)

## Cross-Validation Strategy

- **Time series**: Use TimeSeriesSplit (no future data leakage)
- **Non-temporal**: Use StratifiedKFold (5-fold)
- **Small data**: Use Leave-One-Out or 10-fold

### Overfitting Prevention
1. Keep test set completely separate until final evaluation
2. Use early stopping for XGBoost
3. Monitor train vs validation loss gap
4. Feature selection: remove low-importance features
5. Regularization: reduce max_depth, increase min_samples_leaf

## Bundled Script

```bash
python .claude/skills/ml-ensemble-modeling/scripts/train_ensemble.py \
  --data-file data/features.csv \
  --target outcome \
  --features "feat1,feat2,feat3,feat4,feat5" \
  --model xgboost \
  --test-size 0.2
```

Models available: `random_forest`, `xgboost`
Output: accuracy, AUC, feature importance, predictions, cross-validation scores.

## Model Selection Guide

| Criterion | Random Forest | XGBoost | Logistic Regression |
|-----------|--------------|---------|-------------------|
| Data size | 100+ | 500+ | 20+ |
| Interpretability | Medium | Low | High |
| Tuning needed | Low | High | Low |
| Non-linear | Yes | Yes | No |
| Training speed | Fast | Medium | Fast |
| Overfitting risk | Low | Medium | Low |

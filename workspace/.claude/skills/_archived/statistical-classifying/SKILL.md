# Statistical Classifying

The agent uses this skill when building interpretable classification models for binary outcomes. Trigger phrases: "logistic regression", "classify", "feature importance", "odds ratio", "base rate", "structured prediction".

## Overview

Logistic regression for binary outcome prediction in markets. Preferred over ML when:
- You have structured features with known relationships
- Interpretability matters (want to understand WHY)
- Limited training data (< 1000 observations)
- Need calibrated probability outputs

## Feature Engineering for Prediction Markets

### Universal Features
- **Base rate**: Historical frequency of this outcome type
- **Market age**: Days since market opened (older = more information priced in)
- **Volume**: Total contracts traded (proxy for information)
- **Spread**: Current bid-ask spread (proxy for uncertainty)

### Category-Specific Features

**Economic markets** (Fed rates, GDP, inflation):
- Recent economic indicators (employment, CPI, PMI)
- Fed dot plot / forward guidance
- Yield curve slope
- Prior meeting outcomes

**Election markets**:
- Polling averages (weighted by recency and quality)
- Fundamentals (economy, incumbency, approval rating)
- Historical base rates for similar races

**Weather markets**:
- Forecast model consensus
- Climatological normals
- Recent trend (warming/cooling)

**Sports markets**:
- Elo ratings / power rankings
- Recent form (last 5-10 games)
- Home/away splits
- Injury reports

## Model Building Workflow

1. **Collect features**: Create CSV with one row per historical instance
2. **Feature selection**: Start with 3-5 features, add more if needed
3. **Train/test split**: 80/20 or time-based split for temporal data
4. **Fit model**: Logistic regression with regularization (L2, C=1.0)
5. **Evaluate**: Accuracy, AUC-ROC, calibration curve
6. **Interpret**: Odds ratios for each feature

## Interpreting Odds Ratios

```
Odds Ratio = exp(coefficient)
```

| Odds Ratio | Interpretation |
|-----------|----------------|
| 1.0 | No effect |
| 1.5 | 50% increase in odds per unit increase |
| 2.0 | Doubles the odds |
| 0.5 | Halves the odds |
| 0.1 | 90% reduction in odds |

## Bundled Script

```bash
python .claude/skills/statistical-classifying/scripts/logistic_model.py \
  --data-file data/features.csv \
  --target outcome \
  --features "base_rate,volume,spread,indicator_1" \
  --test-size 0.2
```

Output: coefficients, odds ratios, accuracy, AUC, predictions with probabilities.

## When to Upgrade to ML

Switch to ML ensemble methods when:
- > 1000 training observations
- Non-linear feature interactions suspected
- Many features (> 10)
- Complex temporal dependencies
- Logistic regression accuracy plateaus

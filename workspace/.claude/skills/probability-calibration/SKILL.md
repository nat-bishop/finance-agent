# Probability Calibration

The agent uses this skill when tracking and evaluating prediction accuracy over time. Trigger phrases: "calibration", "Brier score", "am I well-calibrated", "prediction accuracy", "track predictions", "overconfident".

## Overview

Calibration measures whether your predicted probabilities match actual frequencies. A well-calibrated forecaster who says "70% likely" should be right about 70% of the time across many such predictions.

## Metrics

### Brier Score
Measures accuracy of probabilistic predictions:
```
BS = (1/N) * Σ(forecast_i - outcome_i)²
```
- Range: 0 (perfect) to 1 (worst)
- Benchmark: 0.25 (always predicting 50%)
- Good: < 0.15
- Excellent: < 0.10

### Log Loss (Cross-Entropy)
More heavily penalizes confident wrong predictions:
```
LL = -(1/N) * Σ[outcome_i * log(forecast_i) + (1-outcome_i) * log(1-forecast_i)]
```
- Range: 0 (perfect) to ∞
- More sensitive to extreme miscalibration than Brier

### Calibration Curve
Plot predicted probabilities (x-axis) vs actual frequencies (y-axis):
- Perfect calibration = 45° diagonal
- Above diagonal = underconfident (reality is better than predictions)
- Below diagonal = overconfident (reality is worse than predictions)

Bin predictions into groups (e.g., 0-10%, 10-20%, ..., 90-100%) and compute actual win rate in each bin.

## Data Format

Maintain predictions in `data/predictions.csv`:
```csv
date,market_ticker,prediction,confidence,outcome,notes
2025-01-15,FED-25MAR-T4.50,0.65,high,1,Strong labor data supported thesis
2025-01-16,ELEC-25-DEM,0.45,medium,0,Polls shifted after debate
```

Columns:
- `date`: Prediction date (YYYY-MM-DD)
- `market_ticker`: Kalshi market ticker
- `prediction`: Predicted probability (0-1)
- `confidence`: Qualitative confidence (low/medium/high)
- `outcome`: 1 = YES resolved, 0 = NO resolved (blank if unresolved)
- `notes`: Brief rationale

## Diagnosing Biases

| Pattern | Diagnosis | Fix |
|---------|-----------|-----|
| Consistently above diagonal | Underconfident | Push probabilities further from 50% |
| Consistently below diagonal | Overconfident | Pull probabilities toward 50% |
| Worse at high-confidence predictions | Dunning-Kruger | Apply humility discount (shrink toward base rate) |
| Worse in specific category | Category blind spot | Seek additional data sources for that category |
| Brier score improving over time | Learning | Keep tracking, maintain current approach |

## Bundled Script

```bash
python .claude/skills/probability-calibration/scripts/calibrate.py \
  --predictions-file data/predictions.csv \
  --n-bins 10
```

Output: Brier score, log loss, calibration curve data, bias diagnosis.

## Best Practices

1. Record EVERY prediction, not just correct ones (survivorship bias)
2. Predict before looking at market price (anchoring bias)
3. Review calibration monthly with 50+ resolved predictions
4. Use different metrics for different question types (Brier for binary, MAPE for continuous)

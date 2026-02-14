# Monte Carlo Simulation

The agent uses this skill when assessing portfolio risk through simulation. Trigger phrases: "simulate portfolio", "Monte Carlo", "VaR", "CVaR", "risk analysis", "stress test", "what-if scenario".

## Overview

Monte Carlo simulation generates thousands of random portfolio outcomes to estimate risk metrics. Each trial independently resolves every position (win/lose) based on estimated probabilities, then computes portfolio-level P&L.

## Methodology

### Basic Simulation (Independent Positions)
1. For each trial (N=10,000+):
   - For each position: draw uniform random, compare to estimated probability
   - If random < prob: position wins (payout - cost)
   - If random >= prob: position loses (-cost)
   - Sum all P&L for total portfolio outcome
2. Compute statistics across all trials

### Correlated Positions
Use a Gaussian copula to model correlations:
1. Define correlation matrix between positions
2. Generate correlated normal variates using Cholesky decomposition
3. Transform to uniform via CDF, then to binary outcomes
4. This correctly models scenarios where correlated markets move together

### Stress Testing
Layer additional scenarios on top of base simulation:
- **Black swan**: All positions resolve adversely (worst case)
- **Correlation spike**: Increase all correlations by 50% during stress
- **Liquidity crisis**: Apply 2x slippage to exit costs

## Output Metrics

| Metric | Description |
|--------|-------------|
| Expected P&L | Mean portfolio return |
| Median P&L | 50th percentile return |
| VaR (95%) | Value at Risk — maximum loss in 95% of scenarios |
| CVaR (95%) | Conditional VaR — expected loss in worst 5% of scenarios |
| Max Drawdown | Worst single-trial loss |
| Win Rate | % of trials with positive P&L |
| Sharpe Analogue | Mean / StdDev of P&L |
| Skewness | Distribution asymmetry (negative = left tail risk) |

## Bundled Script

```bash
python .claude/skills/monte-carlo-simulation/scripts/simulate.py \
  --positions '[{"ticker":"A","prob":0.6,"size":10,"cost_per":0.45},{"ticker":"B","prob":0.7,"size":5,"cost_per":0.55}]' \
  --n-trials 10000 \
  --correlation-matrix '[[1,0.3],[0.3,1]]'
```

Input: JSON array of positions (ticker, prob, size, cost_per_contract in dollars).
Optional: correlation matrix as nested JSON array.
Output: summary stats + histogram data as JSON.

## Interpretation Guide

- **VaR 95% > 20% of portfolio**: Consider reducing position sizes
- **CVaR >> VaR**: Heavy left tail — high crash risk
- **Win rate < 50% but positive E[P&L]**: Positively skewed (few big wins)
- **Negative skewness**: Most outcomes good but rare bad outcomes are severe

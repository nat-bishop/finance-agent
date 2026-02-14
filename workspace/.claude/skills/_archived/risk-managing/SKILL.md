# Risk Managing

The agent uses this skill when evaluating and managing portfolio-level risk. Trigger phrases: "portfolio risk", "concentration", "drawdown", "rebalance", "exposure", "correlation risk", "VaR", "P&L decomposition", "fee analysis".

## Overview

Portfolio risk management for prediction markets involves:
1. Position concentration limits
2. Correlation detection between markets
3. Drawdown rules and stop-losses
4. P&L variance decomposition
5. Fee impact modeling

## Position Concentration Rules

| Metric | Threshold | Action |
|--------|-----------|--------|
| Single position > 30% of portfolio | Hard limit | Reduce or don't add |
| Top 3 positions > 60% of portfolio | Warning | Diversify |
| Correlated cluster > 40% | Hard limit | Treat correlated positions as one |
| Cash reserve < 20% | Warning | Maintain dry powder |

## Correlation Detection

Markets are correlated when they share underlying drivers:

**High correlation examples:**
- Multiple Fed rate brackets for the same meeting (ρ > 0.8)
- Same-party election markets across states (ρ > 0.5)
- Related economic indicators (inflation + rate hike, ρ > 0.6)

**Detecting correlation:**
1. Check if markets share the same event ticker
2. Check if markets reference the same underlying (rates, elections, etc.)
3. Compute historical price correlation from candlestick data
4. Flag any pair with |ρ| > 0.3

## P&L Variance Decomposition

Decompose realized P&L into sources:

```
Total P&L = Edge Component + Sizing Component + Timing Component + Luck Component
```

- **Edge**: Did your probability estimates have positive expected value?
  - `Σ (model_prob - market_prob) × position_size × outcome`
- **Sizing**: Did you size correctly given your edge?
  - Actual size vs Kelly optimal size × actual outcome
- **Timing**: Did you enter/exit at good prices?
  - `Σ (fill_price - mid_price_at_decision) × direction × size`
- **Luck**: Residual variance from binary outcomes
  - `Total P&L - Edge - Sizing - Timing`

## Fee Modeling

Kalshi's fee structure (approximate):
```
fee_per_contract = price × fee_rate  (on entry)
```

For a round-trip trade:
```
total_fees = entry_fee + exit_fee (if sold before settlement)
           = entry_fee only (if held to settlement)
```

Break-even edge after fees:
```
min_edge = fee_rate / (1 - fee_rate) ≈ fee_rate (for small fee_rate)
```

## Bundled Script

```bash
python .claude/skills/risk-managing/scripts/portfolio_risk.py \
  --positions '[{"ticker":"A","prob":0.6,"size":10,"cost_per":0.45,"category":"fed"}]' \
  --portfolio-value 500 \
  --correlations '{"fed": ["A","B"], "election": ["C","D"]}'
```

Output: concentration analysis, correlation flags, VaR, rebalancing suggestions.

## Drawdown Rules

| Current Drawdown | Action |
|-----------------|--------|
| < 10% | Normal operations |
| 10-20% | Reduce new position sizes by 50% |
| 20-30% | Stop new trades, review all positions |
| > 30% | Liquidate non-core positions |

## Rebalancing Triggers

Rebalance when any of these occur:
1. Position grows to > 30% of portfolio (profit-taking)
2. Correlation cluster exceeds 40%
3. Weekly review shows drift from target allocation
4. Market regime change (volatility spike)

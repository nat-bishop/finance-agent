# Kelly Sizing

The agent uses this skill when sizing positions after determining an edge in a prediction market. Trigger phrases: "size a position", "how much to bet", "Kelly criterion", "optimal bet size", "position sizing".

## Overview

The Kelly Criterion determines the optimal fraction of bankroll to wager given a known edge. For prediction markets (binary outcomes), the formula is:

```
f* = (p * b - q) / b
```

Where:
- `f*` = fraction of bankroll to wager
- `p` = true probability of winning
- `q` = 1 - p (probability of losing)
- `b` = net odds (payout / cost - 1)

For Kalshi binary markets priced in cents (1-99):
- Buying YES at price `c`: cost = c cents, payout = 100 cents if correct
  - `b = (100 - c) / c`
- Buying NO at price `c`: cost = (100 - c) cents, payout = 100 cents if correct
  - `b = c / (100 - c)`

## Fractional Kelly

Full Kelly maximizes long-run growth rate but produces high variance. In practice, use fractional Kelly:

| Fraction | Use Case |
|----------|----------|
| Full (1.0) | Never in practice — too volatile |
| Half (0.5) | Aggressive — high confidence in edge estimate |
| Quarter (0.25) | **Default** — accounts for model uncertainty |
| Eighth (0.125) | Conservative — uncertain edge, correlated positions |

## Multi-Market Kelly

When holding multiple simultaneous positions, the optimal sizing changes because bankroll is shared. For N independent markets:

1. Compute Kelly fraction for each market independently
2. Sum all fractions — if total > 1.0, scale down proportionally
3. Apply fractional Kelly to the scaled amounts

For correlated markets (e.g., multiple Fed rate brackets), reduce sizing further:
- Correlation ρ > 0.5: halve the Kelly fraction
- Correlation ρ > 0.8: quarter the Kelly fraction

## Fee Adjustment

Kalshi fees reduce effective odds. Adjust the payout:
```
effective_payout = payout * (1 - fee_rate)
b_adjusted = (effective_payout - cost) / cost
```

## Bundled Script

Run `scripts/kelly.py` for calculations:

```bash
python .claude/skills/kelly-sizing/scripts/kelly.py \
  --true-prob 0.65 \
  --market-price 55 \
  --bankroll 500 \
  --fraction 0.25 \
  --fee-rate 0.03
```

Output includes: optimal bet size ($), expected growth rate, risk of ruin estimate, edge percentage.

## When NOT to Use Kelly

- Edge estimate has wide confidence interval (>10% uncertainty) → reduce fraction further
- Market is illiquid (spread > 5 cents) → slippage will eat the edge
- Position would exceed portfolio concentration limits
- Near settlement with binary outcome uncertainty

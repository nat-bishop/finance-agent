# Binary Option Pricing

The agent uses this skill when analyzing prediction markets through an options pricing lens. Trigger phrases: "fair value", "option pricing", "time decay", "theta", "Greeks", "implied probability", "volatility surface", "edge calculation".

## Overview

Prediction markets are functionally binary options — they pay $1 if an event occurs, $0 otherwise. Options pricing concepts translate directly:

| Options Concept | Prediction Market Analogue |
|----------------|---------------------------|
| Option premium | Market price (cents) |
| Strike price | Threshold (e.g., "above 4.50%") |
| Expiration | Settlement date |
| Implied vol | Price uncertainty around threshold |
| Delta | Probability sensitivity to underlying |
| Theta | Time decay of option value |
| Vega | Sensitivity to volatility |

## Fair Value Estimation

### From Market Price
The market YES price in cents directly implies a probability:
```
P_implied = yes_price / 100
```

### From Model
If you have an independent probability estimate P_model:
```
Edge = P_model - P_implied
Edge_pct = Edge × 100
```

Trade only when Edge_pct exceeds the minimum threshold (after fees).

## Time Decay (Theta Analogue)

As settlement approaches, extreme probabilities are more "deserved" and middle probabilities decay toward 0 or 100:

```
theta_effect ≈ -σ² / (2 × T_remaining)
```

Where σ is the price volatility and T is time to settlement.

Practical implications:
- **Far from settlement**: Prices revert to 50% more easily (high optionality)
- **Near settlement**: Prices sticky near 0 or 100 (low optionality)
- **At settlement**: Binary — 0 or 100

## Volatility Estimation

### From Price History
Historical volatility from OHLC data:
1. Compute log returns: r_t = ln(close_t / close_{t-1})
2. σ_hist = std(r_t) × sqrt(periods_per_day)

### Implied Volatility
If market price and time to expiry are known, infer the volatility that
makes a simple diffusion model match the market price. The bundled script
iteratively solves for this.

## Greeks Analogues

### Delta
Sensitivity of market price to changes in the underlying:
```
Δ ≈ ΔPrice / ΔUnderlying
```
For binary markets, delta is highest when price ≈ 50 cents.

### Gamma
Rate of change of delta. High gamma near settlement = sudden large price moves.

### Vega
Sensitivity to volatility. Markets with high vega benefit from volatility increases.

## Bundled Script

```bash
python .claude/skills/binary-option-pricing/scripts/pricing.py \
  --market-price 55 \
  --time-to-expiry-days 30 \
  --historical-prices '[50,52,55,53,54,55,57,55,54,56]' \
  --model-prob 0.62
```

Output: fair value estimate, Greeks, edge assessment, time decay rate.

## Edge Assessment Framework

| Edge | Confidence | Action |
|------|-----------|--------|
| > 15% | High | Full Kelly fraction position |
| 10-15% | High | Half the Kelly fraction |
| 5-10% | Medium | Quarter Kelly fraction |
| 5-10% | Low | Monitor, don't trade |
| < 5% | Any | No trade — insufficient edge after fees |

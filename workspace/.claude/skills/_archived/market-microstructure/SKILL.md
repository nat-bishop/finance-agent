# Market Microstructure

The agent uses this skill when analyzing orderbook dynamics, liquidity, and execution quality. Trigger phrases: "orderbook analysis", "liquidity", "spread", "slippage", "market depth", "execution cost", "market impact".

## Overview

Market microstructure analysis examines how the orderbook structure affects trading costs and execution quality. Key concepts:

- **Spread**: Difference between best bid and best ask
- **Mid price**: (best_bid + best_ask) / 2
- **Depth**: Total volume available at each price level
- **Slippage**: Price impact of executing a large order

## Key Metrics

### Spread Analysis
```
Spread = best_ask - best_bid (in cents)
Relative spread = spread / mid_price (percentage)
```

Kalshi spread interpretation:
- 1-2 cents: Very liquid, tight market
- 3-5 cents: Normal liquidity
- 6-10 cents: Moderate liquidity, meaningful execution cost
- >10 cents: Illiquid, consider limit orders only

### Liquidity Score
Composite metric (0-100) based on:
- Spread tightness (40% weight)
- Depth at top 3 levels (30% weight)
- Recent trading volume (30% weight)

### Slippage Estimation
For an order of N contracts:
1. Walk the orderbook from best price
2. Compute volume-weighted average fill price
3. Slippage = avg_fill_price - mid_price

### Market Impact Model
Expected price impact of a trade:
```
impact = spread/2 + k * sqrt(order_size / daily_volume)
```
Where k ≈ 0.1-0.5 depending on market characteristics.

## Orderbook Patterns

| Pattern | Meaning | Action |
|---------|---------|--------|
| Thin on one side | Asymmetric information | Trade carefully on thin side |
| Large resting order | Potential support/resistance | Use as reference level |
| Widening spread | Decreasing confidence | Reduce position sizes |
| Volume spike at price | Consensus forming | Consider if it confirms your thesis |

## Bundled Script

```bash
python .claude/skills/market-microstructure/scripts/liquidity.py \
  --orderbook '{"yes":[[55,100],[54,200],[53,150]],"no":[[46,80],[47,120],[48,90]]}' \
  --order-size 50 \
  --daily-volume 5000
```

Input: orderbook as JSON (yes/no arrays of [price_cents, quantity]).
Output: spread, mid price, liquidity score, slippage for order size, depth profile.

## Execution Best Practices

1. **Always check orderbook before trading** — don't rely on last price
2. **Use limit orders** for positions > 10 contracts
3. **Split large orders** across multiple price levels if depth is thin
4. **Time entries** — avoid trading during low-volume hours
5. **Monitor spread changes** — widening spread may signal upcoming news

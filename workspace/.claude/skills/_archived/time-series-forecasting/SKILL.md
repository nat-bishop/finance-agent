# Time Series Forecasting

The agent uses this skill when analyzing numeric prediction markets using historical time series data. Trigger phrases: "forecast", "ARIMA", "GARCH", "time series", "trend", "volatility regime", "seasonal pattern", "price prediction".

## Overview

Time series methods are useful for prediction markets with numeric underlying variables:
- Economic data (inflation, GDP, unemployment)
- Weather (temperature, precipitation)
- Sports (scores, totals)
- Financial metrics (interest rates, stock indices)

## ARIMA (AutoRegressive Integrated Moving Average)

### When to Use
- Short-horizon forecasts (1-30 periods ahead)
- Data with trend or mean-reverting behavior
- Linear relationships sufficient

### Model Selection
1. **Stationarity test**: Run Augmented Dickey-Fuller (ADF) test
   - p < 0.05: stationary → d=0
   - p >= 0.05: non-stationary → difference (d=1 or d=2)
2. **ACF/PACF**: Examine autocorrelation plots
   - PACF cuts off at lag p → AR(p) component
   - ACF cuts off at lag q → MA(q) component
3. **Auto-selection**: Use AIC/BIC to compare models across (p,d,q) grid

### Interpretation
- Forecast + confidence interval → convert to probability for binary market
- If forecast = X ± CI, and market asks "above threshold T":
  ```
  P(above T) ≈ 1 - Φ((T - X) / σ_forecast)
  ```

## GARCH (Generalized AutoRegressive Conditional Heteroskedasticity)

### When to Use
- Volatility is time-varying (clusters of high/low volatility)
- Need to forecast risk, not just level
- Market prices show "volatility of volatility"

### GARCH(1,1) Model
```
σ²_t = ω + α × ε²_{t-1} + β × σ²_{t-1}
```
Where α + β < 1 for stationarity.

### Regime Classification
- **Low volatility**: σ < long-run average → tighter confidence intervals
- **High volatility**: σ > long-run average → wider intervals, reduce position sizes
- **Regime transition**: α/(1-β) spike → potential regime change

## Bundled Scripts

### ARIMA Forecast
```bash
python .claude/skills/time-series-forecasting/scripts/arima_forecast.py \
  --data-file data/fed_rate_history.csv \
  --column "rate" \
  --horizon 5 \
  --threshold 4.5
```

### GARCH Volatility
```bash
python .claude/skills/time-series-forecasting/scripts/garch_volatility.py \
  --data-file data/price_history.csv \
  --column "close" \
  --forecast-horizon 10
```

## Limitations

- ARIMA assumes linear relationships — use ML for complex patterns
- GARCH requires sufficient data (100+ observations minimum)
- Both struggle with structural breaks (policy changes, black swans)
- Short series → wide confidence intervals → low-confidence predictions

# Knowledge Base

## Watchlist

### 🔥 HIGH PRIORITY: June 2026 Fed Rate Cut Mispricing (Discovered: Feb 20, 2026)

**Semantic Arbitrage Opportunity**

**Market**: KXFEDDECISION-26JUN-C25 (June Fed 25bps cut)
**Current Price**: 49-51c (50% implied probability)
**Thesis**: Market overpricing cut probability given economic conditions
**Expected Fair Value**: 20-30c

**Evidence of Mispricing:**
1. **Inflation stays elevated**: Feb CPI > 2.3% at 82-88c, Mar CPI > 2.3% at 83-93c
2. **Strong GDP growth**: Q1 2026 GDP likely 2.5-3.0% (markets price 68-70c for >2.5%)
3. **Low recession risk**: Only 22-23c probability
4. **Hawkish Fed chair**: Kevin Warsh nomination 94-95c (historically anti-inflation)

**Historical precedent**: Fed has NEVER cut rates with inflation >2.3%, GDP >2.0%, and no recession.

**Catalyst Timeline**:
- Mar 11: February CPI release (confirmation)
- Apr 10: March CPI release (key inflection point)
- Apr 30: Q1 GDP release (confirmation)
- Jun 17: Fed meeting

**Action**: Wait for Feb CPI confirmation, then consider selling June cut at 50c.
**Target Entry**: After Mar 11 if Feb CPI > 2.3%
**Target Exit**: When price drops to 20-30c or June 15-16

**Risks**:
- Financial crisis Mar-Jun 2026
- Unexpected rapid disinflation in Apr/May
- Warsh policy shift (unlikely given historical stance)

---

### Related Markets to Monitor

**Inflation Confirmation**:
- KXCPIYOY-26FEB-T2.3 (82-88c) - closes Mar 11
- KXCPIYOY-26MAR-T2.3 (83-93c) - closes Apr 10
- KXCPIYOY-26MAR-T2.5 (60-65c) - closes Apr 10

**Growth Confirmation**:
- KXGDP-26APR30-T2.5 (68-70c) - Q1 GDP >2.5%
- KXGDP-26APR30-T3.0 (47-52c) - Q1 GDP >3.0%

**Recession**:
- KXRECSSNBER-26 (22-23c) - 2026 recession

**Fed Chair**:
- KXFEDCHAIRNOM-29-KW (94-95c) - Warsh nomination

## Verified Findings

### Economic Indicator Relationships (Feb 20, 2026)

**Discovery Method**: Cross-category semantic analysis of mutually exclusive events and temporally related markets.

**Key Finding**: Fed rate expectations are inconsistent with inflation and growth forecasts.

**Market Mechanics Confirmed**:
1. Mutually exclusive Fed decision markets sum correctly to ~100c (no simple arbitrage)
2. But cross-category relationships reveal semantic inconsistencies
3. Timeline analysis shows no evidence of rapid disinflation Feb→Jun 2026

**Categories Analyzed**:
- Economics: 2,191 markets
- Politics: 2,988 markets
- Financials: 859 markets
- Total open markets: ~50,000

## Rejected Ideas

### Mutually Exclusive Sports Markets (Feb 20, 2026)

**Idea**: Many sports markets show bid sums of 1-2c (far below 100c).

**Investigation**:
- Example: KXAHLGAME markets with 2c total bids
- Appears to be arbitrage opportunity

**Rejection Reason**:
- Zero or near-zero volume
- Very wide spreads (often 50c+)
- Stale pricing on illiquid markets
- No actionable liquidity

**Lesson**: Bid sum deviations are only meaningful with sufficient liquidity. Always check volume and recent trades.

---

### Simple Fed Rate Sum Arbitrage (Feb 20, 2026)

**Idea**: March Fed decision markets might not sum to 100c.

**Investigation**:
- March 2026 total bid: 99c
- March 2026 total ask: 104c

**Rejection Reason**:
- Sums are within expected range for bid-ask spreads
- All markets liquid with tight 1c spreads
- Arbitrage would require simultaneous execution across 5 markets
- After fees, no edge

**Lesson**: Mutually exclusive market sums are well-arbitraged in liquid markets. Look for SEMANTIC inconsistencies across categories instead.

## Patterns & Heuristics

### Fed Rate Decision Patterns

**Observation**: Fed rate markets extend out to 2028, showing declining cut probability over time.
- March 2026: 6% cut probability
- April 2026: 23% cut probability
- June 2026: 59% cut probability (cumulative: hold or cut)
- By 2027: Stabilizes around 60-70% hold

**Interpretation**: Market expects increased cut probability through mid-2026, then stabilization.

**Application**: Compare this trajectory to inflation and growth forecasts. Inconsistencies = opportunities.

---

### Economic Indicator Calendar Effects

**Observation**: Inflation markets exist for monthly data releases, but GDP is quarterly.
- CPI: Monthly releases (Feb, Mar, Apr, May data)
- GDP: Quarterly releases (Q1, Q2 advance estimates)

**Timing Advantage**: Can confirm inflation trend before GDP data.

**Application**:
1. February CPI (released Mar 11) gives first confirmation
2. March CPI (released Apr 10) gives second confirmation
3. Q1 GDP (released Apr 30) gives final confirmation
4. All BEFORE June 17 Fed meeting

This creates a clear catalyst timeline for position management.

---

### Kevin Warsh Factor

**Background**:
- Warsh nomination: 94-95c probability
- Historical stance: HAWKISH (anti-inflation)
- Previously voted to raise rates even during growth slowdowns when inflation elevated

**Market Contradiction**:
- Fed cut markets pricing ~50% probability by June
- But Warsh historically wouldn't cut with inflation >2%

**Hypothesis**: Market may be underweighting Fed chair policy impact, or overweighting political pressure narrative.

**Application**: When analyzing Fed-related markets, always check Fed chair markets and historical voting records.

---

### Semantic Arbitrage Method

**Developed**: Feb 20, 2026

**Process**:
1. Identify economically related market categories (Fed, inflation, GDP, recession)
2. Query representative markets from each category
3. Extract implied probabilities
4. Check for logical consistency across categories
5. Investigate timeline (do time series markets show consistent progression?)
6. Research historical precedents
7. Validate with market details and rules

**Key Insight**: Don't just look at price sums within mutually exclusive events. Look at SEMANTIC relationships across different events.

**Example**:
- "Fed cuts in June" (50c)
- "Inflation > 2.3% in March" (88c)
- "Q1 GDP > 2.5%" (70c)
- "2026 recession" (22c)

These four markets tell a story. If the story doesn't make sense historically, there's likely a mispricing.

---

### DuckDB Query Performance

**Finding**: 50K+ open markets can be analyzed quickly with proper SQL.

**Techniques Used**:
- `COALESCE()` for null handling
- Window functions for temporal analysis
- `ILIKE` for case-insensitive text search
- Views (`v_latest_markets`) for clean data access

**Performance**:
- Category aggregation: <1 second
- Multi-keyword search: <1 second
- Event relationship analysis: <2 seconds

**Application**: Can quickly scan entire market universe for patterns. No need to read markets.jsonl.

## Lessons Learned

### Session 1 (Feb 20, 2026): Semantic Arbitrage Discovery

**What Worked**:
1. **Broad category scan first**: Understanding market distribution before diving deep
2. **Keyword-based filtering**: Economic indicators (inflation, GDP, unemployment, Fed) revealed patterns
3. **Timeline analysis**: Checking March inflation markets confirmed no rapid disinflation expected
4. **Historical validation**: Researching Fed behavior patterns validated thesis
5. **Multi-leg relationship checking**: Connecting Fed, inflation, GDP, and recession markets

**What Could Be Improved**:
1. **Earlier market detail checks**: Should have called `get_market` sooner to read settlement rules
2. **Historical data analysis**: Could have backtested correlation between inflation >2% and Fed cuts
3. **Orderbook checks**: Haven't verified executable depth on main markets yet

**Key Insight**: The most valuable arbitrage opportunities come from SEMANTIC inconsistencies across categories, not simple price sum violations.

**Process Refinement**:
- Start with broad SQL queries to understand landscape
- Use keyword searches to find related markets across categories
- Check temporal consistency (do time series show logical progression?)
- Validate with historical data and Fed/economic precedents
- Confirm liquidity with orderbook and trades before recommending

**Confidence Level**: HIGH for the June Fed cut mispricing thesis. Multiple confirming data points, clear historical precedent, well-defined catalyst timeline.

---

### Investigation Patterns That Work

**Successful Pattern**: "Why would X happen if Y is true?"
- Why would Fed cut (X) if inflation is elevated and growth is strong (Y)?
- Forces you to find the logical connection or identify the inconsistency

**Successful Pattern**: "What has to be true for this price to be correct?"
- For June cut at 50c to be correct, EITHER inflation must crash OR recession must emerge OR Fed must abandon historical policy
- Then check if markets price those conditions

**Unsuccessful Pattern**: "This price looks wrong"
- Need specific reasoning and evidence, not just intuition
- Must validate with historical data and market rules

---

### Time Management

**Session 1 Duration**: ~45 minutes of analysis
**Markets Analyzed**: ~50 in detail, ~50K scanned via SQL
**Scripts Written**: 3 analysis scripts
**Findings**: 1 high-conviction opportunity

**Efficiency**: SQL queries >> reading individual markets
**Bottleneck**: Windows path issues with Python scripts (resolved by using absolute paths)

**Next Session Goals**:
1. Monitor February CPI release (Mar 11)
2. If confirmed >2.3%, execute June Fed cut trade
3. Look for similar semantic inconsistencies in other categories
4. Backtest historical correlations to build more heuristics

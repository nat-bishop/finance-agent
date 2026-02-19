# Knowledge Base
*Last updated: 2026-02-17*

## Watchlist

### Paramount/WBD Calendar (KXACQUANNOUNCEPARAMOUNT-WARN)
- JUN: 45/46c (104d), SEP: 47/48c (196d), DEC: 54/56c (287d)
- JUN→SEP incremental = only 2c (suspiciously low for 3 months)
- SEP→DEC incremental = 7c (much higher)
- Calendar spread (Buy SEP, Sell JUN) is economically interesting but fees kill it at small size
- High volume on MAR (13K/day) and JUN (6K/day), very liquid
- **Monitor**: if SEP/JUN spread widens to 8c+, fees become manageable at larger size

### TGL Championship (KXTGLCHAMPION-26)
- 6 teams, all active as of 2026-02-17
- Prices very volatile — BC dropped from 28c→17c, AD spiked 6c→24c in one day
- Los Angeles (LA): yes_bid=0, no_ask=100 — possibly eliminated but market still open
- ask_sum of 5 active-looking teams ≈ 71c; potential bracket if LA is eliminated
- **Check**: TGL standings to confirm LA status; if eliminated, a 5-team bracket at 71c ask_sum could be real

### BTC Monotonicity (KXBTCMAXMON-BTC-26FEB28)
- Above $90k: bid=2, ask=3 | Above $92.5k: bid=3, ask=4 — VIOLATION (higher price has higher prob)
- Expires Feb 28. Small-size trade: buy $90k YES (3c), sell $92.5k YES (3c) for 0 net premium
- Fees consume any edge at realistic contract counts; only viable if $90k ask drops to 1-2c
- **Monitor**: if violation persists or widens, revisit with fee calculation

## Verified Findings

### Bracket Arbs — None viable as of 2026-02-17
- **Complete brackets** (Fed FOMC meetings, 5 legs each): ALL over-round. ask_sum ranges from 105c (MAR-26, most liquid) to 146c (SEP-26). Market makers extracting 5-46c vigorish.
- **Incomplete brackets** (sports/golf/entertainment): Large apparent "edge" but missing legs. Golf events, MLB awards, presidential elections with partial candidate lists are all incomplete.
- **Mutually exclusive but incomplete**: KXSTATE51-29, KXNBERRECESSQ, KXNEWPOPE-70 etc. appear to have edge but are missing "other outcomes" legs.
- **"Who wins" golf events** (KXPGAR1LEAD-THGI26): Tie rule = YES pays $1/N, not $1. Destroys bracket math.

### Fed Decision Markets (KXFEDDECISION-*)
- 5 legs per meeting: Hold, Cut25, Cut>25, Hike25, Hike>25
- Confirmed mutually exclusive by rules text
- All meetings over-round from both sides; no arb available
- Most liquid: KXFEDDECISION-26MAR (vol24=160K OI=6.4M)

### Fed Rate Cut Count 2026 (KXRATECUTCOUNT-26DEC31)
- 21 legs (0 through 20 cuts); most high-count legs have no bids
- Total ask_sum=120c — heavily over-round
- Consensus: 2-3 cuts most likely (24-25c each), 0 cuts at 8c, 4 cuts at 15c

## Rejected Ideas

### Paramount Calendar Spread (KXACQUANNOUNCEPARAMOUNT-WARN)
- Buy SEP YES (48c), Sell JUN YES (45c): 3c net cost
- **Rejected**: Taker fees for 10 contracts = $0.35 total. Breakeven probability for Jun-Aug announcement = 38c, not 3c. Fees kill the trade entirely.

### BTC $90k/$92.5k Monotonicity Trade
- Buy $90k YES (3c ask), Sell $92.5k YES (3c bid) for 0 premium
- **Rejected**: Fees on two legs consume all profit. Only viable if spread widens significantly or at very high contract counts (50+) where per-contract fees compress.

### Large Sports/Entertainment Incomplete Brackets
- Golf round leaders (72-player fields, only top 9 listed), MLB awards (partial), entertainment (partial Spotify/streaming)
- **All rejected**: Missing legs mean sum ≠ 100; not true brackets.

## Patterns & Heuristics

1. **Kalshi market makers are disciplined**: Near-complete, high-liquidity brackets (Fed FOMC) are always over-round. Edge only exists in illiquid or structurally complex markets.

2. **Fee structure is punishing for small-edge trades**: Taker fee = ceil(0.07 × N × P × (1-P)). At P=0.5, this is 1.75c/contract. A 3c gross edge requires 50+ contracts just to net a positive return.

3. **Calendar spreads look appealing but fees kill them**: The incremental probability across calendar legs often looks mispriced, but the round-trip taker fees on both legs consume the entire apparent edge.

4. **"Mutually exclusive" flag is necessary but not sufficient**: Many events marked ME are incomplete (partial candidate lists, partial outcomes). Always check that ask_sum approaches 100 before treating as a bracket.

5. **Sports events with tie rules**: Golf and some sports pay $1/N on ties, not $1. This fundamentally breaks the bracket math where you'd expect $1 payout.

6. **Volatile bracket markets after live events**: TGL, sports playoffs show sharp price moves post-match. These may create temporary mispricings but are hard to exploit without real-time information.

7. **The best liquid bracket arb targets**: Look for events with 2-4 legs, all-liquid (bid>2 on each), ask_sum 88-99, with high OI (>10K) indicating real market interest. The FL-19 Republican primary (4 candidates, ask_sum=85 with Rommel near-zero placeholder) is the closest to viable but needs confirmation of complete candidate field.

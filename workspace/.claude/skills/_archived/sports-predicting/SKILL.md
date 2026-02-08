# Sports Predicting

The agent uses this skill when analyzing sports prediction markets. Trigger phrases: "Elo rating", "sports prediction", "win probability", "over/under", "matchup", "game prediction", "Poisson model", "score prediction".

## Overview

Sports markets are among the most liquid on Kalshi. Two primary modeling approaches:

1. **Elo ratings**: Win/loss probability from head-to-head skill estimates
2. **Poisson regression**: Score/total prediction for over/under markets

## Elo Rating System

### Core Formula
After a game between players A and B:
```
Expected_A = 1 / (1 + 10^((Rating_B - Rating_A) / 400))
New_Rating_A = Old_Rating_A + K × (Actual_A - Expected_A)
```

Where:
- `Actual_A` = 1 (win), 0.5 (draw), 0 (loss)
- `K` = update factor (higher = more responsive to recent results)

### K-Factor Selection

| Context | K-Factor | Rationale |
|---------|----------|-----------|
| New team/player | 40 | Learn quickly |
| Regular season | 20 | **Default** — balanced |
| Established team | 10 | Slow updates for stable rating |
| Playoff/postseason | 15 | Moderate responsiveness |

### Converting Elo to Win Probability
```
P(A wins) = 1 / (1 + 10^((Elo_B - Elo_A) / 400))
```

### Home Advantage
Add a home-field bonus to the home team's rating:
```
Elo_home_adjusted = Elo_home + home_advantage
```

Typical values:
- NBA: +60 to +100 Elo
- NFL: +40 to +65 Elo
- MLB: +20 to +40 Elo
- Soccer: +50 to +80 Elo

## Poisson Model (Score Prediction)

For predicting total points or individual team scores:

### Expected Goals/Points
```
λ_team = base_rate × attack_strength × defense_weakness
```

Where:
- `base_rate` = league average goals/points per game
- `attack_strength` = team_goals_scored / league_avg_goals
- `defense_weakness` = opponent_goals_conceded / league_avg_goals

### Over/Under Probability
```
P(total > T) = 1 - Poisson_CDF(T, λ_home + λ_away)
```

### Margin of Victory
Compare Poisson distributions for each team to estimate victory margins.

## Bundled Script

```bash
# Elo ratings from game history
python .claude/skills/sports-predicting/scripts/elo_ratings.py \
  --games-file data/nba_games.csv \
  --predict "TeamA vs TeamB" \
  --home-advantage 80

# Format for games CSV:
# date,home_team,away_team,home_score,away_score
```

Output: current Elo ratings, predicted win probability, historical accuracy.

## Data Sources

When analyzing sports markets, the agent should:
1. Check if historical game data exists in `data/`
2. If not, construct it from available information
3. Use at minimum last 2 seasons of data for stable Elo ratings

## Limitations

- Elo doesn't account for roster changes, injuries, or motivation
- Poisson assumes independence of goals (unrealistic for basketball)
- Historical data may not reflect current team strength
- For more nuanced models, combine with ML ensemble methods

# Bayesian Updating

The agent uses this skill when incorporating new evidence to update probability estimates. Trigger phrases: "update probability", "new evidence", "Bayesian", "likelihood ratio", "prior to posterior", "how should I adjust".

## Overview

Bayes' theorem provides a principled way to update beliefs as new evidence arrives:

```
P(H|E) = P(E|H) * P(H) / P(E)
```

In odds form (more practical for sequential updates):

```
Posterior Odds = Prior Odds × Likelihood Ratio
```

Where:
- Prior Odds = P(H) / P(¬H)
- Likelihood Ratio = P(E|H) / P(E|¬H)

## Workflow

### 1. Establish Prior
Start with the market price as prior (unless you have strong reason to diverge):
```
Prior P(H) = market_yes_price / 100
```

### 2. Identify Evidence
For each new piece of evidence, estimate:
- **P(E|H)**: How likely is this evidence if the hypothesis is TRUE?
- **P(E|¬H)**: How likely is this evidence if the hypothesis is FALSE?

The ratio P(E|H) / P(E|¬H) is the **likelihood ratio (LR)**.

### 3. Update
Convert prior to odds, multiply by LR, convert back:
```python
prior_odds = prior / (1 - prior)
posterior_odds = prior_odds * likelihood_ratio
posterior = posterior_odds / (1 + posterior_odds)
```

### 4. Sequential Updates
For multiple independent pieces of evidence, multiply all LRs:
```python
combined_lr = lr_1 * lr_2 * lr_3
posterior_odds = prior_odds * combined_lr
```

## Likelihood Ratio Guide

| LR Range | Strength | Example |
|----------|----------|---------|
| 1.0 | No evidence | Irrelevant information |
| 1.5-2.0 | Weak | Mildly suggestive poll |
| 2.0-5.0 | Moderate | Directional economic data |
| 5.0-10.0 | Strong | Official policy statement |
| 10.0-20.0 | Very strong | Authoritative confirmation |
| >20.0 | Decisive | Nearly certain proof |

Same scale applies in reverse (LR < 1.0 = evidence against hypothesis).

## Common Pitfalls

1. **Base rate neglect**: Always start from a reasonable prior, not 50/50
2. **Double-counting**: Don't update on the same evidence twice (e.g., a poll and a news article about that poll)
3. **Correlation**: If two pieces of evidence are correlated, the combined LR is less than LR1 × LR2
4. **Overconfidence in LR estimates**: When uncertain about the LR, use conservative values closer to 1.0

## Implementation Guidance

The agent should write custom update scripts in `analysis/` when performing Bayesian analysis. Template:

```python
import json

def bayesian_update(prior: float, evidence: list[dict]) -> dict:
    """Update prior through sequential evidence.

    evidence: [{"description": "...", "lr": 2.5}, ...]
    """
    odds = prior / (1 - prior)
    updates = []

    for e in evidence:
        lr = e["lr"]
        old_prob = odds / (1 + odds)
        odds *= lr
        new_prob = odds / (1 + odds)
        updates.append({
            "evidence": e["description"],
            "likelihood_ratio": lr,
            "prob_before": round(old_prob, 4),
            "prob_after": round(new_prob, 4),
            "shift": round(new_prob - old_prob, 4),
        })

    posterior = odds / (1 + odds)
    return {
        "prior": prior,
        "posterior": round(posterior, 4),
        "total_shift": round(posterior - prior, 4),
        "n_updates": len(evidence),
        "updates": updates,
    }
```

## Information Value

Before seeking new evidence, estimate its expected value:
```
Value of Information = |E[posterior] - prior| × cost_of_wrong_decision
```

High-value evidence to prioritize:
- Official data releases (economic indicators, election results)
- Policy decisions (Fed statements, legislation)
- Domain expert analysis (not media commentary)

Low-value evidence to deprioritize:
- Social media sentiment (noisy, often already priced in)
- Pundit opinions (low calibration, high confidence)
- Historical analogies (past performance ≠ future results)

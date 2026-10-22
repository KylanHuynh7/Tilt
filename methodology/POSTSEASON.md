# Postseason Calibration Layer — Methodology Document
## Version 0.1
**Author:** Kylan Huynh
**Status:** APPROVED 2026-10-12 (PS-1 one λ per sport; PS-2 pass rule as written). Applies to NFL, MLB and college football. **College football was retired 2026-10-21** before its test; its fitted λ stays in the frozen artifact as a record but is no longer used.
**Last updated:** 2026-10-12

## 1. Why

Three one-shot tests (2022–2025) flagged postseason calibration:

| Sport | Postseason n | Postseason LL | Postseason ECE | Regular-season LL |
| --- | --- | --- | --- | --- |
| MLB | 171 | **0.711** (worse than a coin flip) | 0.103 | ≈ 0.677 |
| College football (bowls + CFP) | 176 | **0.685** (barely below a coin flip) | 0.091 | ≈ 0.566 |
| NFL | 52 | 0.586 (better than its regular season) | 0.170 | 0.637 |

**Hypothesis:** in the postseason, rating gaps overstate the real difference between teams.
- Playoff fields are narrowed to good teams.
- MLB aces start more often, and bullpens are shortened.
- College bowls have opt-outs, interim coaches and long layoffs.

**Contamination disclosure:** this proposal was motivated by those test results. They become *fitting* data here, never test data again (§4).

## 2. Model change

The pre-game probability for a postseason game is pulled toward 50%:

```
p_post = σ(λ · logit(p))        0 < λ ≤ 1
```

- **λ = 1** reproduces the current models exactly.
- **λ < 1** shrinks every postseason probability toward 0.5.
- **Regular-season games are untouched.**
- **Rating updates are unchanged:** Elo still updates with the raw p. Only the published forecast changes, so no sport's ratings are re-frozen.

**[DECISION PS-1] One λ per sport or one shared λ.**
- Recommended: **one per sport.** The causes differ (opt-outs vs short benches vs aces).
- *Alternative:* one pooled λ (more data per estimate, but it assumes a single cause).

## 3. Fitting λ

- **Grid:** λ ∈ {0.50, 0.55, …, 0.95, 1.00}. The selected λ minimises postseason log-loss on the sport's fitting window.
- **Fitting windows:** every postseason from validation through the old test, with the frozen v1 ratings.
  - NFL 2015–2025, ≈ 130 games.
  - MLB 2015–2025, ≈ 420 games.
  - College football 2014–2025, ≈ 470 games.
- **Pre-registered expectations:**
  - MLB and college football λ land in [0.5, 0.85].
  - NFL λ lands at 0.9 or above, since its playoff LL was already good.
  - A λ of 1.0 for MLB or college football means the flagged weakness was noise, and the layer is not shipped for that sport.

## 4. Test (one-shot, the next untouched postseason per sport)

| Sport | Test games | Available |
| --- | --- | --- |
| MLB | 2026 postseason (in progress; no metric has been computed on it) | after the World Series, ~November 2026 |
| College football | 2026 bowls + CFP | after the CFP final, ~January 2027 |
| NFL | 2026 playoffs | after the Super Bowl, ~February 2027 |

**[DECISION PS-2] Pass rule.** Recommended:
- the layer **passes for a sport if its postseason log-loss with shrinkage is lower than without it**, on that sport's test games;
- also reported: pooled across sports, and ECE.

**Honest power note:** one postseason is 13 (NFL) to about 45 games. A single test can only reject a large effect, so results accumulate: every later postseason is reported with the same frozen λ (not refitted).

## 5. Display

- Postseason game cards and pages show the shrunk probability, with "playoff-adjusted (λ = …)".
- The raw Elo probability stays visible in the game-page breakdown.
- If a sport's test fails, its layer is switched off and the result documented.

## 6. Fit results (2026-10-12, `artifacts/postseason/lambdas.json`)

| Sport | Fitting window | n | λ | LL raw → shrunk | Expectation |
| --- | --- | --- | --- | --- | --- |
| NFL | 2015–2025 | 133 | **1.00** (layer off) | 0.62093 → 0.62093 | ✓ (≥ 0.9) |
| MLB | 2015–2025 | 440 | **0.70** | 0.68863 → 0.68765 | ✓ ([0.5, 0.85]) |
| College football | 2014–2025 | 480 | **0.80** | 0.66391 → 0.66200 | ✓ ([0.5, 0.85]) |

- **The gains on the fitting window are small** (0.001–0.002 LL).
- **NFL keeps its raw probabilities.** That supports reading its 2022–2025 playoff flag (n = 52) as noise.
- **MLB and college football postseason probabilities are now published shrunk**, with "playoff-adjusted" on the game card and the raw Elo value on hover. The live models still take the raw pre-game value they were trained on.
- **The MLB 2026 test postseason was already under way** when λ was fitted (LCS round). No metric was computed on any 2026 game, and λ was fitted only on 2015–2025.
- **The one-shot evaluator** (`scripts/postseason_evaluate.py --sport … --confirm`) refuses to run until that sport's final is in the data.

## 10. What I will not do

- Refit λ on a test postseason.
- Apply the layer to regular-season games.
- Use betting lines or any third-party forecast.

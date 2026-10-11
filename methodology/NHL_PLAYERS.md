# NHL Player Projections — Methodology Document
## Version 0.2
**Author:** Kylan Huynh
**Status:** Approved 2026-10-11, all seven decisions as recommended (P-1 NHL, P-3 test 2023-24 → 2025-26 and P-7 hide-unless-pass explicitly; P-2, P-4, P-5 and P-6 as written).

**Amendment log:**
- *v0.2 (2026-10-11, during the first trial ingest, before any model code or bulk download):* The §3 coverage threshold is lowered from 16 to **12 skaters per team**. The trial season contained a genuine 15-skater game (New Jersey on 2010-10-11, under the salary cap), so 16 would have rejected real lineups. 12 still catches truncated box scores. Games below 16 are counted in the manifest.
**Last updated:** 2026-10-11

Same project rules as the team models:
- written and approved before any code;
- targets fixed before data is examined;
- one-shot test with `--confirm` and no-overwrite guards;
- limitations in §13;
- a CHANGELOG entry and commit after every phase.

---

## 1. Question

**Before each game, for every skater expected to dress: what is the probability they record at least one point, and at least one goal?**

These are binary and checkable after every game: the player either got a point or didn't. They support the same calibration-honest scoring as the team models (log-loss, Brier, ECE). Expected points (λ, below) are shown as the model's intermediate quantity. They are evaluated only through the two probabilities.

**[DECISION P-1] Which sport first.** Recommended: **NHL**.
- The official NHL API has per-game box scores for every player: lineups back to 1967-68, ice time from 1998-99.
- No third-party data and no new terms of use are needed.
- A working player model is also the foundation for NHL v4 ("Interpretation P", METHODOLOGY.md §17), where player value feeds team ratings.
- *Alternatives:*
  - **MLB:** P(hit), P(home run). MLB Stats API, excellent, under MLB AM's non-commercial terms.
  - **NBA:** points thresholds. ESPN box scores; continuous stats make for a less clean binary target.

Each later sport gets its own document.

**[DECISION P-2] What is projected.** Recommended: **P(≥1 point) and P(≥1 goal)** for skaters.
- Goalies are excluded from v1 (a different question: saves and goals against).
- *Alternative:* add P(≥3 shots on goal) as a third target.

## 2. Pre-registered expectations

These are predictions, not pass criteria. The pass criteria are in §6.
- **Base rates:** P(point) averages about 0.30 per skater-game (forwards ≈ 0.35, defense ≈ 0.22), and P(goal) about 0.12. That puts base-rate log-loss near 0.61 (point) and 0.37 (goal).
- **Expected log-loss:** the model lands near 0.58–0.60 (point) and 0.34–0.36 (goal). Single-game scoring is mostly noise; the achievable improvement over base rates is small.
- **Effect size:** ice time and the player's own scoring rate dominate. Opponent strength and home ice are small effects.
- **Weakest groups:**
  - players in their first 20 NHL games (little history);
  - players whose role changed suddenly: line promotion, injury return, trade.

## 3. Data

- **Source:** `api-web.nhle.com/v1/gamecenter/{id}/boxscore`, the regular season and playoffs.
- **Fields read per skater-game:** player id, team, position (F/D), time on ice, goals, assists, points, shots on goal.
- **Coverage rule:** a season is used only if every completed game has a box score with ≥ 12 skaters per team (v0.2; was 16).
- **Shared ingest:** the same box-score ingest serves NHL v3 (METHODOLOGY.md §20, DECISION V3-1). It is built once.
- **Never read:** odds or betting lines of any kind, and no third-party projections.

**[DECISION P-3] Split.** Recommended, all seasons complete, so the test is one-shot and runs now:

| Role | Seasons |
| --- | --- |
| Warm-up (histories build, nothing scored) | 1998-99 → 2009-10 |
| Validation (tune) | 2010-11 → 2022-23 |
| Test (touched once) | 2023-24, 2024-25, 2025-26 |

*Alternative:* test on 2026-27 (cleanest, but no verdict until mid-2027).

## 4. Model

For skater *i* before game *g*, using only games before *g*:

```
TOI_hat  = decayed mean of the player's TOI       (half-life H_toi games; prior: m_toi games at the position's debut TOI)
rate_hat = (Σ w_k·x_k + m·r_pos) / (Σ w_k·toi_k/60 + m)     per-60 rate of the event, shrunk to the position rate
             w_k = 0.5^(age_k / H),  age in the player's own games, across seasons
λ        = rate_hat · TOI_hat/60 · opp^γ · home^(±1)
P(≥1)    = 1 − exp(−λ)
```

- **Position values:**
  - `r_pos` is the previous season's league rate per 60 for the player's position (F or D).
  - The position debut TOI is the previous season's mean TOI in players' first 10 career games.
- **Opponent:** `opp` is the opponent's decayed goals allowed per game divided by the league mean (half-life 20 team games; 1.0 for a team's first game).
- **Home ice:** `home^(±1)` multiplies λ for the home skater and divides it for the away skater.
- **Fitting:** points and goals use the same form and are tuned separately.

**Tuning grid** (each event; lowest validation log-loss, ties broken by ECE then Brier):

```
H      ∈ {20, 40, 80, 160, 320}     games
m      ∈ {1, 2, 4, 8}               hours of TOI at the position rate
H_toi  ∈ {5, 10, 20}                games
γ      ∈ {0, 0.5, 1}
home   ∈ {1.00, 1.03, 1.06}
```

That is 540 cells per event. The pre-registered expectations are optimal H in [40, 160] and γ > 0. A γ of 0 means the opponent term carries no signal at this resolution.

**[DECISION P-4] Opponent strength source.** Recommended: **the opponent's decayed goals allowed**, computed from the same box scores.
- *Alternative:* the team Elo model. Its hyperparameters were tuned on seasons that overlap this test window, which would be a contamination.

## 5. Who gets a projection

**[DECISION P-5] Recommended:**
- **Evaluation:** score only skaters who actually dressed (the box-score lineup). Projecting a scratched player is a different question.
- **Live:**
  - project each team's current NHL roster minus players ESPN rules out;
  - mark the projection "lineup not confirmed" until the game starts;
  - after puck drop, use the actual box-score lineup.
- A healthy scratch can still receive a pre-game projection (§13).

## 6. Pass criteria (fixed before data is examined)

On the test seasons, separately for **point** and **goal**:

1. **Beats Baseline A**, the previous season's position base rate, on log-loss.
2. **Beats Baseline B**, the player's points (or goals) per game over their last 82 games turned into a probability via Poisson (position rate if fewer than 10 games), on log-loss. This is the natural "how often does this player score?" heuristic.
3. **ECE < 0.02.**
4. **Top-decile calibration:** in the highest 10% of predictions, |mean predicted − observed rate| < 0.03.

**Reported, not targets:**
- forwards vs defense;
- first 20 career games vs the rest;
- each test season;
- regular season vs playoffs.

**Flags:** any group with ECE > 0.04, or playoffs worse than the regular season by > 0.01 log-loss.

**[DECISION P-6] Targets.** Recommended as written. *Alternative:* drop criterion 4 (top-decile) as too strict for goals, whose top decile is mostly stars at about 0.35.

## 7. Display

- **Game pages:** each skater row in the lineup shows P(point) and P(goal).
- **Player cards:** show the next-game projection.
- **Dashboard:** gains "Likeliest scorers tonight" (top 10 by P(goal)).
- **Shipping:** nothing ships if the §6 test fails. Projections then stay off the site, with the result documented.

**[DECISION P-7] Ship rule.** Recommended as written: show only if all §6 criteria pass. *Alternative:* show with a visible "failed its test" label, as the team models do for flagged weaknesses.

## 10. What I will not do

- Read betting lines, prop odds or third-party projections.
- Touch the test seasons more than once.
- Change the model after seeing test results.
- Project goalies in v1.

## 13. Known limitations (initial)

- **Lineup uncertainty:** pre-game projections can't know healthy scratches or line changes announced at warm-ups.
- **No linemate or power-play context:** a player promoted to the top line shows up only through their rising TOI, with a lag.
- **No ice time before 1998-99,** which is why the warm-up starts there.
- **Player identity:** NHL player ids; matching ESPN injury reports to NHL ids is by name and team, so it can occasionally miss.

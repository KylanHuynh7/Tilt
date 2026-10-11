# NFL Rating System — Methodology Document
## Version 1.0
**Author:** Kylan Huynh
**Status:** v1 frozen and evaluated 2026-10-11 — **all four §6 criteria PASS** on 2022–2025 (playoff ECE flag fired; see §13). APPROVED 2026-10-11 — all six **[DECISION]** items resolved as recommended. Any later change to §§3–6 or §12 is a version-tagged amendment.
**Last updated:** 2026-10-11

**Amendment log:**
- *v0.1-draft (2026-10-11):* First draft, written after a data-availability probe and before any NFL ingest, rating code, or metric.
- *v1.0 (2026-10-11):* Author approved with every [DECISION] as recommended: (1) test 2022–2025, (2) MOV on/off in the grid with ties at M = 1, (3) no K_playoff ≥ K_regular constraint, (4) QB adjustment deferred to v2, (5) v1 thresholds LL < 0.660, Brier 0.200–0.235, ECE < 0.05, must beat home-rate baseline, (6) v1.1 live targets pre-registered as in §12. No other text changed.

---

> Governs the NFL model the way `methodology/NBA.md` governs the NBA model: a separate model with its own split, parameters, freeze, and one-shot test evaluation. "Inherits NBA §N" means that section applies with NFL seasons substituted. College football is **out of scope**; it would get its own document.

### What was seen before this draft (contamination disclosure)

- **nflverse `games.csv`:** column names; row counts by season and by `game_type` (REG / WC / DIV / CON / SB); the `location` split (7,446 Home, 102 Neutral); the set of team codes. **No scores, results, margins, or win rates were printed or computed.**
- **nflverse play-by-play:** that a file exists for 1999, 2005, 2018 and 2025; the 2018 file's column names and row count (47,109).
- **ESPN NFL scoreboard:** one matchup row for 2026-10-11 (PHI at JAX, neutral site, scheduled) and the field names of a 2025-10-12 completed game. No scores were read.

The author's priors come from public knowledge: FiveThirtyEight's NFL Elo (K = 20, MOV multiplier, ~65 Elo home field, ~1/3 regression), and the widely reported decline of NFL home-field advantage since roughly 2020.

---

## Section 1 — Problem statement and scope

Interpretable NFL team ratings producing calibrated pre-game win probabilities, evaluated once on held-out seasons, shown alongside NHL and NBA.

- **NFL v1:** game-by-game Elo with home-field advantage and margin of victory, pre-game probabilities, a one-shot calibration evaluation, and a dashboard (trajectories, this week's games, calibration).
- **NFL v1.1 (same freeze cycle, after v1 is frozen):** live in-game win probability (§12).
- **Deferred:** quarterback adjustment (DECISION 4), Super Bowl / playoff simulation, rest and bye-week effects, weather, injuries, travel.

Not a betting tool, not a power ranking, not a Vegas competitor.

---

## Section 2 — Hypotheses and predictions

**Expected to do well:** mismatches between clearly different teams mid-season.

**Expected to do poorly:**
- *Quarterback changes.* A starting QB's absence moves NFL win probability more than any other single factor, and a team-level Elo can't see it. Expected to be the largest error source.
- *Early season* (weeks 1–4). Offseason turnover is large and the season is short, so carry-over ratings are stale for a big share of the games.
- *Late regular season* (weeks 17–18). Clinched teams rest starters and eliminated teams play backups. §2 of the NBA document predicted the wrong direction for the analogous effect, so the NFL expectation is stated as **either direction, flagged if late-segment ECE > 2× mid-segment.**
- *2020* (empty or limited stadiums). Home-field advantage was near zero. No special handling.

**Pre-registered expectations (test set):**
- Log-loss **< 0.660**; Brier **0.200–0.235**; ECE **< 0.05**.
- The ECE bound is looser than NHL / NBA (0.04) because a four-season NFL test has ~1,100 games, and 10-bucket ECE noise at that size is roughly ±0.02.
- The model beats the **home-rate baseline** on log-loss (inherits NBA §6).
- Tuned home bump **20–60 Elo.** This prior is anchored on the post-2015 era, after NBA's 50–110 prior missed by anchoring on old seasons. Outside 0–120 suggests a wiring bug.
- MOV beats binary outcomes on validation.

---

## Section 3 — Data sources, pipeline, deployment

**Results and schedule: nflverse `games.csv`** (`github.com/nflverse/nfldata`, open data, CC-BY). Covers 1999 → current schedule. Fields used: `game_id, season, game_type, week, gameday, home_team, away_team, home_score, away_score, location, overtime`.

**Fields never read (§10):** `spread_line`, `total_line`, `home_moneyline`, `away_moneyline`, `*_spread_odds`, `under_odds`, `over_odds`. The QB id/name columns are factual and allowed, but unused in v1 (DECISION 4).

**Play-by-play (v1.1 only):** nflverse `play_by_play_{season}.parquet`, about 19 MB per season. Only game-state columns are read: `game_id, qtr, game_seconds_remaining, posteam, home_team, yardline_100, down, ydstogo, total_home_score, total_away_score`. **Every model-output column is never read:** `wp, def_wp, home_wp, away_wp, vegas_wp, vegas_home_wp, ep, epa, …`. Raw files aren't committed; compact extracted samples are (as with NBA play-by-play).

**Live data: ESPN NFL scoreboard** (same client pattern as NBA): this week's games, score, clock, period. During games ESPN adds a `situation` block (down, distance, field position, possession), which is **unverified until observed during a live game** and must be checked before v1.1 ships. ESPN team abbreviations are mapped to nflverse codes (e.g. WSH → WAS, LAR → LA).

**Coverage rule (inherits NBA §3):** a season enters the model only if its regular-season count matches the schedule within one game. That schedule is 31 teams × 16 / 2 = 248 in 1999–2001, 256 in 2002–2020, and 272 from 2021 (17 games). The probe matched 1999 (248), 2002 (256), 2020 (256), 2021 (272) and 2025 (272). 2022's cancelled BUF–CIN game (271 played) is within tolerance.

**Game filter:** REG at K_regular; WC / DIV / CON / SB at K_playoff; preseason not in the data.

**Neutral sites:** `location == "Neutral"` gets no home bump. That covers Super Bowls and international games (London, Mexico City, Germany, São Paulo, …).

**Season id:** the starting year (the 2025 season runs Sep 2025 → Feb 2026).

---

## Section 4 — Train / validation / test split

- **Warm-up:** 1999 → 2014 (16 seasons).
- **Validation:** 2015 → 2021 (7 seasons, ~1,870 games incl. playoffs; includes 2020).
- **Test (touched once):** 2022, 2023, 2024, 2025, all complete, ~1,140 games.
- **Live:** 2026 onward on frozen parameters.

**[DECISION 1] Test window.** Recommendation: four seasons. NFL seasons are a fifth the size of NBA seasons; two seasons (~570 games) would make every metric noisy (NHL §13.J). The cost is a shorter validation window.

**Regression:** `R_new = 1500 + carry × (R − 1500)` at each season boundary.

**Lineage** (rating inherited, no reset): St. Louis Rams → Los Angeles Rams (2016, `STL` → `LA`), San Diego Chargers → Los Angeles Chargers (2017, `SD` → `LAC`), Oakland Raiders → Las Vegas Raiders (2020, `OAK` → `LV`). Washington's renames don't change its code. **Expansion:** Houston Texans (2002) start at 1500, no regression (inherits NBA §4). The 1999 Browns are not treated as an expansion team; every team starts at 1500 in 1999 anyway.

---

## Section 5 — Model specification

```
P(home wins) = 1 / (1 + 10 ^ ((R_away − R_home − H·h) / 400))    h = 0 at neutral sites
R_new        = R + K × M × (W − P)
```

**Outcomes:** win 1, loss 0, **tie 0.5.** Ties are rare (a handful per decade) but real.

**MOV multiplier** (FiveThirtyEight NFL form; constants fixed, not tuned):

```
M = ln(|MOV| + 1) × 2.2 / (0.001 × D + 2.2)
D = R_winner − R_loser, home bump included on whichever side had it
```

**Ties under MOV:** `ln(0 + 1) = 0` would freeze ratings on a tie between unequal teams, so **ties use M = 1** (plain Elo update toward 0.5).

**Overtime:** no extra weighting. A one-score OT result is already a small-MOV result.

**[DECISION 2] MOV in the grid.** Recommendation: on/off switch, as NBA.

**[DECISION 3] K_playoff ≥ K_regular constraint.** Recommendation: **don't impose it** (NHL §13.C, NBA §13). With only 11–13 playoff games a season, expect K_playoff to be weakly identified; the grid result is reported, not trusted.

**[DECISION 4] Quarterback adjustment.** Recommendation: **defer to NFL v2.** FiveThirtyEight's QB adjustment needs a per-QB value model, a second rating system inside this one (the same reasoning NHL v3 used to reject player ratings). v1 ships without it, and the QB limitation is pre-registered (§2) as the expected largest error source. It also leaves v2 a clear, testable feature.

**Grid** (lowest validation LL, ties by ECE then Brier):

```
K_regular ∈ {10, 15, 20, 25, 30, 40}
K_playoff ∈ {10, 20, 30, 40}
carry     ∈ {0.50, 0.60, 0.67, 0.75, 0.85}
H         ∈ {0, 20, 35, 50, 65, 80}
mov       ∈ {off, on}
```

1,440 cells, ranges from priors.

**Not in v1:** QB, injuries, rest / bye weeks, weather, travel, coaching changes.

---

## Section 6 — Evaluation

Primary **LL < 0.660**; secondary **Brier 0.200–0.235**, **ECE < 0.05**; **must beat the home-rate baseline on LL.** Baselines: naive 0.5, home-rate (validation constant, 0.5 at neutral sites), static rating (end of validation). All reported for every breakdown regardless of flattery.

**Breakdowns emitted in the single pass (inherits the NBA lesson):**
- per test season;
- regular vs playoffs;
- week segments 1–4 / 5–16 / 17–18 (for 16-game seasons, 1–4 / 5–15 / 16–17);
- neutral site;
- calibration buckets with n for each.

**[DECISION 5] Thresholds.** Recommendation as written.

---

## Section 7 — Backtest protocol

Inherits NHL §7 / NBA §7.

## Section 8 — Failure modes

Inherits NBA §8 (home-advantage drift flagged before freezing, rating bounds [1100, 1900], ±1 league mean, loud data-source failure), plus:
- **2020 home-field collapse.** If the 2020 validation-season home rate is far from its neighbours, it is reported. It is not excluded (NHL §10 #4).

## Section 9 — Stopping criteria

Inherits NBA §9, with NFL artifact paths (`artifacts/nfl/`, `results/nfl/`) and the NFL pill flipping to `live`.

## Section 10 — What I will not do

Inherits NBA §10, with NFL test seasons (2022–2025) substituted. Explicitly, the following are never read as inputs, targets or benchmarks: nflverse betting columns, nflfastR / nflverse model outputs (`wp`, `vegas_wp`, `ep`, `epa`, …), and ESPN `odds` / predictor fields.

## Section 11 — Claude Code instructions

Inherits NBA §11.

---

## Section 12 — NFL v1.1: live in-game win probability

Built after v1 is frozen; it uses the frozen pre-game probability.

**Model (interpretable logistic, five coefficients):**

```
logit P(home wins | state) = β0
                           + β1 · pre · (τ / 3600)
                           + β2 · d / sqrt(m + 1)
                           + β3 · s · (1 − y / 100) / sqrt(m + 1)
                           + β4 · s / sqrt(m + 1)

pre = logit of the frozen pre-game P(home wins)
τ   = seconds left in regulation (OT: seconds left in the OT period); m = τ / 60
d   = home score − away score
s   = +1 if the home team has the ball, −1 if the away team does, 0 if neither
y   = yards from the possessing team to the opponent's end zone (yardline_100)
```

Reading: the pre-game edge fades with time, a lead matters more as time runs out, and having the ball (β4) and having it close to scoring (β3) matter more late. Down, distance and timeouts are **not** in v1.1 (§13).

- **Training:** nflverse play-by-play 2004 → 2014 (warm-up seasons only; skips the first five Elo burn-in seasons). One sample per play with a defined possession and down.
- **Evaluation:** once on 2022–2025.

**[DECISION 6] Live-model targets.** The NBA live model had none, so its evaluation could only describe results, not pass or fail them. Recommendation: pre-register them now.
1. Beat the pre-game-held baseline on LL in every quarter.
2. Overall ECE < 0.05.
3. Three structural checks:
   - at kickoff, within 0.02 of the pre-game probability;
   - monotone in d;
   - leading by 17+ with ≤ 2 minutes left gives ≥ 0.97.

---

## Section 13 — Known limitations (initial)

- **No quarterback model** (DECISION 4): the biggest known omission.
- **Small samples:** ~285 games a season; four test seasons still give only ~1,100 games.
- **Single league-wide home bump:** ignores Denver altitude, dome teams, travel and time zones. The post-2020 decline is the NHL v2 failure mode (NHL §13.C) waiting to happen.
- **No pre-1999 history:** nflverse game data starts in 1999.
- **Houston (2002) seeded at 1500,** overstating an expansion team early.
- **Live state depends on an unverified ESPN `situation` block** until first observed live.
- **Play-by-play models are trained on 2004–2014 football.** Rule changes since (kickoff rules 2024, OT rules 2022 / 2025, PAT distance 2015) shift game-state values.
- **Frozen parameters (N3, 2026-10-11):** `K_regular 20, K_playoff 10, carry 0.60, H 35, mov on`, from the 1,440-cell grid on 2015–2021. Validation (n = 1,889): LL 0.63402, Brier 0.22067, ECE 0.01781. Baselines: naive LL 0.69315, home-rate LL 0.68852, static rating LL 0.73021. Validation numbers only; the test pass is what counts.
  - *H = 35 is inside the pre-registered 20–60.*
  - *MOV helps:* LL 0.63402 vs 0.63952 for the best MOV-off cell.
  - *K_playoff < K_regular again,* as in NHL and NBA. K_playoff = 10 is the grid floor. The best cell with K_playoff ≥ K_regular is 0.00014 LL worse.
- **§8 home-advantage drift flag — FIRED before freezing.** Home win rate (non-neutral games, ties as 0.5) by validation season: 2015 54.0%, 2016 58.6%, 2017 57.5%, 2018 60.1%, 2019 52.3%, 2020 50.4%, 2021 51.4%. That's a drop of roughly 7–9 points between the first and second halves of the window, the same shape that sank NHL v2 (NHL §13.C). Per §8 the response is to document it, not to add a time-varying term mid-cycle. The single frozen H = 35 (about 55% for equal teams) sits between the two regimes. If the 2022–25 home rate stays near 51%, expect the test calibration to show home teams over-predicted.
- **Test evaluation (N4, run once 2026-10-11, `results/nfl/test_evaluation.json`):** 2022–2025, n = 1,139. Model **LL 0.63440 (PASS < 0.660), Brier 0.22135 (PASS 0.200–0.235), ECE 0.02870 (PASS < 0.05)**, and it beats the home-rate baseline (LL 0.68768). **All four §6 criteria pass.** Naive LL 0.69315; static rating LL 0.72076. Locked per §10 #2.
  - ***Playoff flag fired:*** playoff ECE **0.1701** (n = 52) exceeds the inherited 0.08 threshold. Fifty-two games across ten buckets is very thin, so much of this is noise, but the flag is reported prominently as the rule requires. Playoff LL (0.586) is actually lower than regular-season LL (0.637).
  - *Late-season flag did not fire:* late/mid ECE ratio 1.71 (late 0.0721, mid 0.0421).
  - *Early season is weaker:* weeks 1–4 ECE 0.0590 and LL 0.661, as §2 expected.
  - *Per season:* 2022 ECE 0.0347, **2023 0.0629**, 2024 0.0488, 2025 0.0397. Two of four seasons sit near or over the target on their own.
  - *The home-advantage collapse did not persist.* The observed test home rate is 55.3%, close to what H = 35 implies, so the §8 drift risk flagged at freeze did not materialize as a test miss.
  - *Neutral-site games:* n = 28, ECE 0.258 — noise at that size.
- **Dashboard / API (N5):**
  - *"This week" is whatever ESPN's default scoreboard calls the current week.* Between Tuesday and Thursday it may still show the finished week.
  - *Champion = winner of the season's last `SB` game.* It reproduces KC 2019, TB 2020, LA 2021, KC 2022–23, PHI 2024.
  - *Pre-game probabilities ignore starting-QB news* (DECISION 4). A backup starting is invisible to the model and to the card.
  - *ESPN `situation` parsing is written* (possession, yards to end zone, down, distance) but still unverified against a live game. It isn't used until v1.1.
  - *Similar team colors* (e.g. PHI and JAX, both teal-green) make the team-colored probability bar harder to read; the percentages are authoritative (NHL §13.I).
- **No logos:** inherits NHL §13.I.

---

## Decisions (resolved 2026-10-11 — all as recommended)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Test window | 2022–2025 (four seasons, ~1,140 games) |
| 2 | Margin of victory | On/off in the grid (ties always M = 1) |
| 3 | K_playoff ≥ K_regular | Do not impose |
| 4 | QB adjustment | Defer to NFL v2; pre-registered as the largest expected error |
| 5 | v1 thresholds | LL < 0.660, Brier 0.200–0.235, ECE < 0.05, beat home-rate baseline |
| 6 | v1.1 live targets | Pre-register: beat held baseline every quarter, ECE < 0.05, three structural checks |

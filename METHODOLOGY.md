# NHL Rating System — Methodology Document
## Version 2.1
**Author:** Kylan Huynh
**Status:** v1 shipped and locked (commit `f7548f6`). v2 in flight; the v1 model and v1 evaluation are immutable per §10 #2.
**Last updated:** May 2026

**Amendment log:**
- *v1.1 (2026-05-17):* Six pre-code clarifications folded into the relevant sections before any implementation work. No model behavior is introduced that was not implied by v1.0; all changes resolve ambiguities flagged during a methodology review. Specifically: (1) expansion-team rating + decay interaction (Section 4), (2) franchise identity persistence across relocations (Section 4), (3) tie outcome weight for pre-2005-06 seasons (Section 5), (4) explicit uniform playoff K-factor across all rounds (Section 5), (5) `/games/today` frozen-parameter invariant (Sections 5 and 11), (6) Brier score upper bound tightened from 0.250 to 0.245 (Sections 2 and 6). See CHANGELOG.md for the corresponding commit.
- *v1.2 (2026-05-17):* Resolves an ambiguity introduced in v1.1 §4 regarding the California Seals / Cleveland Barons → Minnesota North Stars merger. The v1.1 language "pre-merger games count toward the surviving franchise's rating" left open whether the absorbed franchise's pre-merger rating was discarded, averaged, or transferred at the 1978 merger. v1.2 specifies the **simple average** rule: at the start of 1978-79, the surviving franchise's rating is set to the arithmetic mean of its own and the absorbed franchise's final 1977-78 ratings, after which the standard between-season decay applies. This rule is the most defensible reading of the v1.1 intent and is the only merger ever applied in modern NHL history; if a future merger occurs the same rule will apply by default. Resolved before any backtest evaluation was run; no parameter tuning or test-set exposure has occurred. See CHANGELOG.md.
- *v2.0 (2026-05-18):* Begins the v2 methodology with the first of four pre-registered v2 features (the appendix lists Monte Carlo Cup probabilities, live in-game probability updates, hero-chart live updates, and home-ice advantage). v2.0 introduces **home-ice advantage** as a new tunable rating parameter and defines the v2 train / validation / test split. Crucially, v2 is a new model with its own freeze cycle; the v1 model parameters and v1 test-set results are immutable per §10 #2 and remain the canonical v1 record. See the new Section 12 below and CHANGELOG.md.
- *v2.1 (2026-05-18):* Adds **Monte Carlo Cup probabilities** — the second of the four pre-registered v2 features. No change to the rating model itself; Cup probabilities are a forward projection from current ratings, not an evaluation of model accuracy against future outcomes. Defines the sim algorithm (per-game rating updates within a single run, 10,000 sims per call), the data inputs (parquet for current state, derived bracket), and how this surface relates to the §10 #1 test-set quarantine (it does not). See the new Section 14 below.

---

> This document governs all design, implementation, and evaluation decisions for the NHL Rating System project. It is written before any code is written. Its purpose is to prevent post-hoc rationalization of results, silent model changes, and scope creep. Every section is a binding commitment. When in doubt, refer back here.

---

## Section 1 — Problem statement and scope

This project builds a custom, interpretable rating system for NHL teams that produces calibrated win probabilities on a game-by-game basis. The system updates after each game result, reflecting changes in estimated team strength across a full season and into the playoffs. The primary output is a probability estimate for each game, not a leaderboard or power ranking.

**V1 scope:** in-season rating updates, game-level win probability, and honest calibration evaluation against a naive baseline and Vegas closing lines. No offseason roster modeling, no Monte Carlo Cup simulation, no player-level modeling, no live in-game probabilities, no home ice advantage adjustment.

**V2 scope (planned):** Monte Carlo playoff simulation producing Cup win probabilities that update after each game. Live game probability updates reflected in the hero trajectory chart. Home ice advantage adjustment.

**V3 scope (planned):** Roster-shock modeling incorporating trades and free agency signings as rating adjustments. Series-context probability adjustment.

This project is not a score predictor. It is not a power ranking. It will not claim to beat Vegas. Its distinguishing commitment is honest calibration reporting regardless of results.

The audience for this project is someone who wants to understand team strength trajectories over time, explore historical NHL seasons, and see honest probabilities with the methodology fully documented — not a bettor. Vegas lines are not the benchmark because sportsbooks are markets, not prediction models. Their goal is balanced action, not accurate probability. This project's value is interpretability and calibration honesty, which Vegas does not publish.

---

## Section 2 — Hypotheses and predictions

These predictions are written before model evaluation. They exist to prevent post-hoc rationalization of results.

**What the model is expected to do well:**
The rating system should produce stable, well-calibrated probabilities for mid-season games between teams with meaningfully different ratings. When one team is rated significantly higher than another, the model's predicted win probability should reflect that gap reliably across a large sample of similar matchups. Calibration in the 45–65% probability range is expected to be strongest since most NHL games fall in that range and the rating system has the most data to anchor those predictions.

**What the model is expected to do poorly:**

*Early-season games* (roughly the first 15 games of any season) are expected to show the worst calibration. Ratings from the prior season carry over at 75%, but roster changes, new coaching systems, and player development mean early-season team strength is genuinely uncertain. The model has no mechanism to reflect that uncertainty — it will express false confidence in early games.

*Playoff games between closely-rated teams* are expected to be the weakest prediction environment in the model. When two teams are within 20–30 rating points of each other, the model's win probability hovers near 50% and a single goalie performance or injury can decide a series. The model cannot account for this. Expected calibration in close playoff matchups is poor.

*Games following long road trips and back-to-back schedules* are expected to show systematic bias. The model treats every game as equivalent regardless of schedule context. Teams playing their fourth road game in six days are disadvantaged in ways the rating system cannot see. This will likely appear as underprediction of road losses in dense schedule stretches.

*Hot-streak upsets* are a known lag problem. The rating system updates after every game but K=6 means a five-game winning streak moves a team's rating by roughly 15–20 points — not enough to capture a team that has genuinely gotten hot. Upsets driven by recent form will be systematically underpredicted.

**What the model explicitly does not try to predict:**
In-game win probability, series momentum, goalie-specific performance, and the impact of individual player injuries. These are documented omissions, not oversights.

**The pre-registered expectation for overall calibration:**
The model is expected to produce a Brier score in the range of 0.235–0.245 on the held-out test set, beating the naive home-team-wins baseline but not matching Vegas closing lines. If the Brier score exceeds 0.245 on the test set, the model has failed its pre-registered target and that result will be reported as a failure, not reframed. The upper bound was tightened from 0.250 to 0.245 in v1.1 so that the Brier target is roughly equivalent in stringency to the log-loss target in Section 6.

**On historical seasons prior to 1967-68:**
Seasons from 1917-18 through 1966-67 are available in the dashboard for historical exploration only. They are excluded from all model training, validation, and evaluation. No calibration claims are made about this era. A disclaimer is displayed prominently whenever a pre-1967 season is selected.

---

## Section 3 — Data sources, pipeline, and deployment architecture

**Primary data source:** NHL API (the same idempotent pipeline architecture used in Variance97). Game results, boxscore data, team standings, and schedule data are pulled from this source. The pipeline is run on a daily cron job during active season periods to keep ratings current.

**Historical data coverage:**
- 1917-18 through 1966-67: legacy seasons, available in the dashboard explorer but excluded from all model training and evaluation. Data consistency in this era is not guaranteed. A disclaimer is shown whenever these seasons are selected.
- 1967-68 onward: full training and evaluation data. This is the expansion era and represents the modern NHL structure.

**COVID season handling in the pipeline:**
2019-20 (71 games played) and 2020-21 (56 games played) are ingested normally. No special pipeline logic is applied. The shortened schedules are a documented limitation handled at the modeling level, not the pipeline level.

**Earliest available season:** 1917-18, the first recorded NHL season.

**Deployment architecture:**
The project uses a decoupled three-layer architecture:

*Data and model layer:* Python. NHL API pipeline, rating system computation, and backtest logic. Runs on a scheduled cron job to update ratings after each game day.

*API layer:* FastAPI. Exposes the following endpoints to the frontend:
- `/ratings/current` — current ratings for all 32 teams
- `/ratings/history/{season}` — full game-by-game rating trajectory for a given season
- `/games/today` — today's matchups with win probabilities
- `/calibration/current` — current season calibration metrics

Deployed on Railway or Render free tier.

*Frontend layer:* React. Deployed on Vercel. Consumes the FastAPI endpoints. No model logic lives in the frontend — it is a display layer only. The project author commits to understanding React component structure, useState, and useEffect before frontend development begins. Claude Code writes frontend code but does not own it — the author must be able to read, understand, and debug every component.

**Frontend aesthetic standard:**
The dashboard matches the fidelity of the v1 mockup produced during the planning phase. This means a clean flat layout, readable typography, a full-width trajectory chart as the hero element, and a tabbed games view with probability bars. Streamlit is explicitly not used. Design quality is a secondary priority behind model correctness and calibration honesty, but the frontend should reflect the seriousness of the underlying work.

**API contract:**
The API contract between the Python backend and the React frontend is defined and agreed upon before either layer is built. Frontend and backend development do not begin simultaneously.

---

## Section 4 — Train / validation / test split

The model is trained and evaluated on NHL seasons from 1967-68 through 2024-25. Seasons prior to 1967-68 are available in the historical explorer but are excluded from all model training, validation, and evaluation due to data consistency concerns in the pre-expansion era.

**The split is as follows:**
- Training: 1967-68 through 2020-21
- Validation (hyperparameter tuning only): 2021-22 and 2022-23
- Test (held out, touched exactly once): 2023-24 and 2024-25

**COVID season handling:**
The COVID-shortened seasons (2019-20 and 2020-21) are included in training but flagged. Game counts for those seasons are normalized before computing any per-season aggregates. They are not used as standalone validation seasons because the shortened schedule artificially inflates rating volatility.

**Test set rule:**
The test set is examined exactly once, at final evaluation. Any model change made after observing test set results invalidates the evaluation and requires re-splitting. This rule has no exceptions.

**Season boundaries:**
Season boundaries are respected strictly. No information from season N+1 is used when rating games in season N. Between-season rating carryover follows the decay rule below.

**Between-season rating decay:**
At the start of each new season, team ratings are partially regressed toward the league mean of 1500 using a carry factor of 0.75. A team ending season N at rating R begins season N+1 at:

```
R_new = 1500 + 0.75 × (R − 1500)
```

This rule applies uniformly to all teams. Expansion teams begin at exactly 1500. The carry factor of 0.75 is a tunable hyperparameter during validation but must be frozen before test set evaluation.

**Expansion teams and the decay rule (v1.1 clarification):**
An expansion team's first season starts at exactly 1500 with no decay step applied (there is no prior-season rating to decay). The decay rule applies normally at every season boundary from season 2 onward. This is the assumed behavior and is now explicit. It applies identically to historical expansions (e.g., the 1967-68 expansion six) and modern expansion teams (Vegas 2017-18, Seattle 2021-22).

**Franchise identity across relocations (v1.1 clarification, updated v1.2):**
Franchise rating persists across relocations. When a franchise relocates, the new-city team inherits the prior-city team's most recent rating without any reset, and that rating continues to evolve under the same decay and update rules. Examples in the training and validation windows: Atlanta Flames → Calgary Flames (1980), Colorado Rockies → New Jersey Devils (1982), Minnesota North Stars → Dallas Stars (1993), Quebec Nordiques → Colorado Avalanche (1995), Hartford Whalers → Carolina Hurricanes (1997), Atlanta Thrashers → Winnipeg Jets (2011).

**Franchise mergers (v1.2 resolution):**
A merger is treated differently from a relocation because two pre-merger ratings exist on the day of the merger and one must yield to the other. The rule: at the start of the season following the merger, the surviving franchise's rating is set to the **arithmetic mean** of the surviving franchise's and the absorbed franchise's final pre-merger ratings. The standard between-season decay (carry = 0.75) is then applied to that averaged rating. The absorbed franchise stops existing in the rating state from that boundary onward.

The only merger this rule applies to in NHL history is the 1978 California Golden Seals / Cleveland Barons (OAK → CGS → CLE lineage) merging into the Minnesota North Stars (later Dallas Stars). At the 1978-79 boundary, the North Stars' new rating is `mean(R_MNS_1977-78, R_CLE_1977-78)`. The same rule will be applied by default to any future merger; a future amendment can override it before that merger occurs.

This decision is for modeling simplicity and best matches the v1.1 wording "pre-merger games count toward the surviving franchise's rating" — both lineages contribute equally to the post-merger state. It is not a claim that relocated or merged teams retain their old fans' team identity.

---

## Section 5 — Model specification

The rating system is a modified Elo variant with hockey-specific adjustments to game outcome weighting and update magnitude.

**Initial conditions:**
All teams begin the training period (1967-68) at a rating of 1500. The league mean is fixed at 1500 by construction — every rating point gained by one team is lost by another.

**Win probability function:**
The expected win probability for team A against team B is:

```
P(A wins) = 1 / (1 + 10^((R_B − R_A) / 400))
```

The divisor 400 is standard and controls how steeply win probability scales with rating difference. It is not tuned during validation.

**Outcome weighting:**
Game results are not binary. Outcomes are weighted as follows prior to computing the rating update:

| Result | Weight |
|---|---|
| Regulation win | 1.00 |
| OT win | 0.75 |
| SO win | 0.65 |
| Tie (pre-2005-06 only) | 0.50 |
| SO loss | 0.35 |
| OT loss | 0.25 |
| Regulation loss | 0.00 |

The reasoning: a shootout is more luck-driven than OT, so it receives less credit in both directions. These are starting values and are tunable during validation.

**Tie handling (v1.1 clarification):**
The shootout was introduced in 2005-06. Regular-season ties existed from 1967-68 through 2004-05 — a large share of the training data. A tie receives a weight of 0.50 for both teams, which is the natural choice consistent with the expected-value interpretation of the outcome weights (both teams earned half a "result"). The tie weight is fixed, not tunable, because it is mechanically determined by the symmetry of the outcome and there is no defensible asymmetric alternative. From 2005-06 onward there are no ties in the data; the row is inapplicable and must be unreachable in the rating update path for those seasons.

**Rating update rule:**
After each game, both teams' ratings are updated:

```
R_A_new = R_A + K × (W_A − P(A wins))
```

Where W_A is the weighted outcome for team A from the table above, and K is the update factor.

**K-factor:**
K controls how much a single game moves a team's rating. Starting values:
- Regular season: K = 6
- Playoff games: K = 10

Playoff games receive a higher K because they are higher-information signals — teams are at full effort and the opponent pool is non-random. K values are tuned during validation and frozen before test set evaluation.

**Playoff K uniformity (v1.1 clarification):**
K=10 is uniform across all playoff games regardless of round or series state. A Round 1 Game 1 and a Stanley Cup Final Game 7 are weighted identically. Series-context adjustment (e.g., elimination-game multipliers, lead-state adjustments) is explicitly deferred to V3 per Section 5's "what this model does not include in v1" list and per the appendix roadmap. Adding any round- or game-state-dependent K to v1 is out of scope.

**`/games/today` and frozen parameters (v1.1 clarification):**
The `/games/today` endpoint computes pre-game win probabilities using the rating system. To remain consistent with Section 10 #8 ("I will not re-run the pipeline on historical data after tuning the model on live 2025-26 season results"), the parameters used to power those live probabilities must be exactly the parameters frozen at the end of validation. The rating *state* updates as new game results land — that is the system functioning as designed — but the *parameters* (K-factor, outcome weights, decay carry factor) must not be retuned against 2025-26 outcomes. This is enforced at the code level: the parameter set used by `/games/today` is loaded from the frozen-parameters artifact produced at the end of validation, and any code path that recomputes parameters from current-season data is a defect.

**Home ice:**
Home ice advantage is a known, real effect in the NHL but is excluded from v1. All win probabilities are computed as if games were played on neutral ice. This is a documented limitation — home/away splits in the calibration plot may reveal systematic miscalibration as a direct result. Home ice adjustment is a candidate for v2.

**What this model does not include in v1:**
Player-level ratings, goalie separation, roster shock from trades or free agency, score-state adjustments, rest day adjustments, back-to-back game penalties, series-context adjustment, and live in-game probabilities. These are documented omissions, not oversights. Their absence is a limitation to be reported honestly in the evaluation.

---

## Section 6 — Evaluation metrics with thresholds

The primary evaluation metric is log loss. Secondary metrics are Brier score and calibration ECE (Expected Calibration Error). All three are reported on the held-out test set regardless of which is most flattering.

**Primary metric — log loss:**
Target: below 0.685 on the test set. The theoretical baseline for a model that predicts 50% for every game is 0.693. Beating 0.685 represents a meaningful improvement over the uninformed baseline. Failing to beat 0.685 is a documented failure.

**Secondary metric — Brier score:**
Target: between 0.235 and 0.245 as pre-registered in Section 2 (tightened from 0.250 to 0.245 in v1.1 so the Brier target is roughly equivalent in stringency to the log-loss target). A Brier score above 0.245 means the model has failed its pre-registered target and will be reported as such. A Brier score above 0.250 additionally means the model has not beaten the naive baseline.

**Secondary metric — calibration ECE:**
Target: below 0.04. ECE measures the average gap between predicted probability and actual win rate across probability buckets. An ECE of 0.04 means predictions are on average within 4 percentage points of reality across all buckets. The calibration plot is published regardless of ECE value.

**Benchmark comparisons:**
The model is compared against two baselines in order of priority:
1. Naive baseline: always predict 50% for every game. This is the floor. Failing to beat it ends the evaluation.
2. Higher-rated team wins baseline: predict the higher-rated team wins with probability derived purely from the rating gap, using no K-factor update logic. This tests whether the update mechanism adds value over static ratings.

Vegas closing lines are noted as context but are not used as a success threshold. Matching Vegas is not a goal of this project.

**Reporting rule:**
All six numbers — log loss, Brier score, and ECE for both the model and both baselines — are reported in a single table in the project README. No metric is omitted. If the model beats the naive baseline on log loss but not Brier score, both results are reported and neither is buried.

---

## Section 7 — Backtest protocol

The backtest uses a walk-forward expanding window. The model trains on all available data up to game N before predicting game N+1. No future information is used at any point.

**Protocol steps in order:**

1. Initialize all team ratings at 1500 for the first game of the 1967-68 season.
2. For each game in chronological order through the end of the 2020-21 season (training period): compute the predicted win probability using current ratings, then update ratings using the outcome. Predictions are not recorded during this phase — this is warm-up only.
3. For each game in 2021-22 and 2022-23 (validation period): compute predicted win probability before updating ratings, record the prediction and actual outcome. Use these records to tune K-factor, SO/OT weights, and the between-season decay parameter. Freeze all parameters at the end of this phase.
4. For each game in 2023-24 and 2024-25 (test period): compute predicted win probability using frozen parameters, record predictions. Do not update parameters. Do not look at aggregate metrics until all test games are processed.
5. Compute all metrics in Section 6 on the test set predictions. Report as-is.

**Look-ahead bias rules:**
No information is used that was not available before the game's scheduled start time. This applies to ratings (updated only after game completion), roster data in future versions (joined by transaction date, not pull date), and standings (not used as model inputs in v1).

**Season boundary handling:**
Between seasons, apply the decay rule from Section 4 before the first game of the new season. The decay is applied once per team per season boundary, not per game.

**COVID season handling:**
2019-20 (71 games played of 82) and 2020-21 (56 games played of 82) are included in training. K-factor is not adjusted for these seasons. The shortened schedules mean ratings are noisier at season end for those years — this is accepted and noted as a limitation. Between-season decay is applied normally.

---

## Section 8 — Failure modes

The following failure modes are identified in advance. If any are observed during validation or test evaluation, they are documented as findings, not quietly fixed.

**Rating inflation or deflation over time.**
If the league average drifts meaningfully above or below 1500 over many seasons, the between-season decay rule has a bug. Symptom: by the 2020s, most teams have ratings clustered far from 1500. Fix if caught during validation only — not after test set evaluation.

**Early-season miscalibration.**
Expected and pre-registered in Section 2. The calibration plot will be broken out by season segment (games 1–15, 16–50, 51–82) to make this visible. This is reported as a finding, not corrected by adding an early-season K-factor adjustment post-hoc.

**Playoff miscalibration.**
Expected and pre-registered. Playoff games will be evaluated separately from regular season games in the calibration plot. If ECE for playoff games exceeds 0.08, it is flagged prominently in the project README.

**Look-ahead bias detection.**
If model performance on the training set is dramatically better than validation (e.g. Brier score below 0.220 on training vs above 0.245 on validation), this is a signal of look-ahead bias or data leakage in the pipeline. The pipeline is audited for date integrity before proceeding to test evaluation. The test set is not touched during this audit.

**Rating convergence failure.**
If two teams with a 100+ point rating gap are producing win probabilities outside the expected 68–75% range, the win probability function has an implementation error. This is caught during a pre-evaluation sanity check on the formula before any metrics are computed.

**COVID season instability.**
If ratings show abnormal volatility specifically in 2019-20 and 2020-21 relative to adjacent seasons, the shortened schedule is the likely cause. This is noted as a known limitation and no corrective action is taken — it is documented in the README.

**Calibration plot systematic skew.**
If the calibration plot shows the model's line consistently above or below the diagonal across all buckets (not just one), the model is systematically overconfident or underconfident league-wide. This is reported as a primary finding and investigated for a formula error before assuming it is a genuine model limitation.

---

## Section 9 — Stopping criteria

V1 is complete when all of the following conditions are met, in order. No condition can be skipped.

1. All sections of this methodology document are written and author-approved before any code is written.

2. The data pipeline pulls clean game results from 1917-18 through the current season, with pre-1967 seasons flagged as legacy and excluded from model evaluation.

3. The rating system produces a valid rating for all 32 current NHL teams after processing every game in the training period, with no team rating below 1200 or above 1800 (a sanity boundary — values outside this range indicate a formula error).

4. The backtest runs cleanly through the full protocol in Section 7 with no look-ahead bias flags triggered.

5. All three metrics in Section 6 are computed on the test set and recorded. Regardless of whether thresholds are met, the numbers are written down and do not change.

6. The calibration plot is generated and added to the project README. It is not cropped, filtered, or selectively shown. All probability buckets with more than 30 predictions are displayed.

7. The React frontend deployed on Vercel renders the trajectory chart for all 32 teams with eliminated team lines dropping correctly, the season selector populates correctly for all available seasons, the games tab shows today's matchups with raw rating-based probabilities and the disclaimer from Section 2, and all three FastAPI endpoints return valid responses in production.

8. A CHANGELOG.md exists with an entry for every meaningful code change.

9. The project README contains: a plain-English description of the methodology, the full metrics table from Section 6, the calibration plot, a link to this methodology document, and the student project disclaimer.

10. The author has reviewed all of the above and made a manual git commit with the message `v1 complete` before considering the project shipped.

V1 is not complete if the model underperforms thresholds. Underperformance is a valid, shippable finding. The project ships with honest results regardless of outcome.

---

## Section 10 — What I will not do

The following constraints are binding and cannot be waived mid-project.

1. I will not examine test set results (2023-24 or 2024-25 seasons) until model development is complete and the Section 5 specification is frozen. Freezing means all parameters are written down and no further changes are permitted without a full re-evaluation from scratch.

2. I will not change any model parameter after observing test set performance. If the test set results are poor, I will report them as-is and document the failure mode. I will not re-tune and re-run.

3. I will not add features to the model that were not pre-specified in Section 5 without restarting the backtest from scratch. Feature additions mid-evaluation are data leakage.

4. I will not silently exclude seasons or game subsets from evaluation because they hurt my metrics. Any exclusion must be pre-specified in Section 4 with a documented reason.

5. I will not report only the metric that makes my model look best. Log loss and Brier score are both reported regardless of which is more flattering. The calibration plot is published regardless of how ugly it is.

6. I will not claim my model beats a benchmark unless it beats it on the held-out test set, not the training or validation set.

7. I will not use data that was unavailable at game time. Roster information, injury reports, and trade data are joined using the date the information became public, not the date I pulled it. Look-ahead bias in the data pipeline invalidates the evaluation.

8. I will not re-run the pipeline on historical data after tuning the model on live 2025-26 season results and present those numbers as a legitimate backtest.

---

## Section 11 — Claude Code instructions and version control

This section governs how Claude Code interacts with this project.

**Git control — non-negotiable rules:**
Claude Code will not push any commits to the repository under any circumstances. All commits are made manually by the project author after reviewing changes. Claude Code's role is to write, edit, and explain code — not to manage version history.

Claude Code will not stage files with `git add`, will not run `git commit`, and will not run `git push`. If asked to do any of these, Claude Code should decline and remind the author to commit manually.

Branching strategy is the author's decision. Claude Code works on whatever branch is currently checked out and does not create, merge, or delete branches without explicit instruction.

**Methodology doc review process:**
Before writing any code for a new feature or version, Claude Code will be given the relevant sections of this methodology document and asked to flag:
- Any ambiguity in the specification that would require an implementation assumption
- Any technical decision that conflicts with a constraint in Sections 4, 5, or 10
- Any scope that appears to belong to a later version

Claude Code will not begin implementation until the author has resolved all flagged items.

**Version changelog:**
Every meaningful code change is accompanied by a one-line entry in CHANGELOG.md describing what changed and why. Claude Code writes the changelog entry as part of the same work unit as the code change. The author reviews and commits both together.

**V2 and V3 review:**
When v1 is complete and shipped, this methodology document will be extended with v2 specifications before any v2 code is written. Claude Code will review the v2 spec using the same process above. The same applies to v3. No version's code is written before its methodology section is reviewed and author-approved.

---

## Appendix — Version roadmap summary

| Feature | Version |
|---|---|
| Game-by-game rating updates | V1 |
| Win probability per game | V1 |
| Calibration evaluation and plot | V1 |
| Historical season explorer (1917-18 onward) | V1 |
| React frontend on Vercel | V1 |
| FastAPI backend on Railway/Render | V1 |
| Monte Carlo Cup win probabilities | V2 |
| Live in-game probability updates | V2 |
| Hero chart updates with live game results | V2 |
| Home ice advantage adjustment | V2 |
| Roster-shock from trades and free agency | V3 |
| Series-context probability adjustment | V3 |

---

*This document was completed before any code was written. It is the source of truth for all v1 decisions. Disagreements between this document and the codebase are resolved in favor of this document unless a formal amendment is made and committed to the repository.*

---

## Section 12 — v2.0 amendment: home-ice advantage

**Motivation.** The v1 calibration plot (`results/test_evaluation.json`) shows the model systematically under-predicting the home team's win rate in every probability bucket by roughly 3 to 8 percentage points. §5 of the v1 methodology anticipated this exact pattern as the expected signature of omitting home ice ("All win probabilities are computed as if games were played on neutral ice. … home/away splits in the calibration plot may reveal systematic miscalibration as a direct result. Home ice adjustment is a candidate for v2."). v2.0 is that adjustment.

**Model change.** A new tunable parameter `HOME_BUMP`, measured in Elo rating points, is added to the win-probability formula. When computing the probability that the home team beats the away team:

```
P(home wins) = 1 / (1 + 10 ^ ((R_away - R_home - HOME_BUMP) / 400))
```

`HOME_BUMP = 0` exactly reproduces the v1 model. A positive value tilts predicted probabilities toward the home team. The standard NHL historical home-advantage is approximately a 3-percent absolute win-rate increase, which corresponds to roughly 40–60 Elo points. The grid search over the validation period will find the value that minimizes log-loss while honoring the §6 pass criteria.

**Constraint.** `HOME_BUMP ≥ 0`. A negative bump would imply away teams are favored by venue, which has no theoretical basis. The constraint is enforced in the grid construction so the unconstrained winner is the same as the constrained winner.

**Symmetry.** The bump is applied to the home rating only, not subtracted from the away rating. The Elo win-probability function is symmetric in this construction: `P(home wins) + P(away wins) = 1` is preserved.

**Rating-update rule.** The K-factor update mechanism is unchanged from v1. Only the *predicted* probability shifts by the bump; the actual home/away outcome is scored against the bumped prediction. This means home teams that overperform the bumped prediction still earn rating points, and vice versa.

**v2 train / validation / test split.**

- *v2 train:* 1967-68 through 2020-21. Identical to v1.
- *v2 validation:* 2021-22, 2022-23, 2023-24, 2024-25. The former v1 test seasons are folded into validation. This is permissible because v2 is a separate model with its own evaluation; v1's results on 2023-24 and 2024-25 are locked at their v1 values regardless of v2's evaluation on the same data.
- *v2 test:* 2025-26. Held out, touched exactly once at v2 final evaluation. The 2025-26 regular season completed in April 2026; the playoffs are concluding in June 2026. v2 final evaluation runs after the Stanley Cup Final.

**v2 grid search dimensions.**

```
K_regular   ∈ {4, 6, 8, 10, 12}
K_playoff   ∈ {6, 10, 14, 18}     constraint: K_playoff ≥ K_regular  (§5)
decay_carry ∈ {0.65, 0.70, 0.75, 0.80, 0.85}
HOME_BUMP   ∈ {0, 20, 40, 60, 80, 100}   constraint: HOME_BUMP ≥ 0
```

100 v1 grid cells × 6 HOME_BUMP values = 600 v2 grid cells. Selection by lowest log-loss with deterministic tiebreaks (ECE then Brier).

**v1 artifacts preserved.** The v1 frozen-params artifact is preserved as `backend/artifacts/frozen_params_v1.json`. The v1 test-evaluation result is preserved as `backend/results/test_evaluation_v1.json`. These represent the v1 model's locked record and must not be modified. The active artifact (`frozen_params.json`) tracks the current production model.

**v2.0 pre-registered expectations.**

- The optimal `HOME_BUMP` will be in the range of 30 to 70 Elo points. A value below 20 or above 100 would suggest a model wiring bug.
- The validation log-loss should improve by at least 0.005 versus v1 on the same validation seasons (2021-22 + 2022-23). Less improvement would indicate home ice is doing less than expected and other model issues dominate.
- The validation ECE should drop below 0.04 on the v1 validation window, since the v1 ECE miss (0.0422) was hypothesized to be home-ice driven.
- On the new v2 test set (2025-26), the expected Brier band remains 0.235–0.245 as in v1.2. The expected ECE target is < 0.04 (v1's primary miss should be resolved).

**v2.0 stopping criteria** are inherited from §9 with one additional condition: the v1 artifacts (`frozen_params_v1.json` and `test_evaluation_v1.json`) must exist at commit time and must be byte-identical to their v1 values. A diff against v1 is run as part of the v2 release checklist.

**What v2.0 explicitly does not include.** The other three pre-registered v2 features (Monte Carlo Cup probabilities, live in-game probability updates, hero-chart live updates) are scope for subsequent v2.x amendments. v2.0 is intentionally narrow so the home-ice fix can be evaluated in isolation.

---

## Section 13 — Known limitations and ongoing uncertainties

This section consolidates limitations that have surfaced during v1 development and v2.0 work. Material that appears elsewhere in this document is cross-referenced rather than repeated. The intent is a single page that an honest reader can use to bound what this model does and does not claim, without hunting through other sections.

### A. Features the model does not include (scope-deferred)

These are documented omissions, not oversights. Their absence is a limitation of this version of the model, not a flaw in the methodology.

- **Player-level ratings, goalie separation, roster-shock from trades or free agency.** Deferred to v3 per §5 and the appendix.
- **Monte Carlo Cup probabilities, live in-game probability updates, hero-chart live updates.** Pre-registered v2 scope; not in v2.0 (§12).
- **Series-context adjustment for playoff games.** Game 7 of the Cup Final is weighted identically to Round 1 Game 1 (uniform K_playoff per §5 v1.1). Deferred to v3.
- **Schedule context.** Back-to-back games, dense road trips, jet lag, and 4-in-6-night stretches are not represented. §2 pre-registers that "games following long road trips and back-to-back schedules are expected to show systematic bias." No corrective term exists in v2.0.
- **Score-state and within-game state.** v1 and v2.0 produce pre-game probabilities only. Live in-game WP is a deferred v2 feature.
- **Team-specific home advantage.** The v2.0 `HOME_BUMP` is a single league-wide constant. Some venues (Edmonton, Winnipeg, Nashville) historically confer larger home advantages than others. Modeling team-specific or venue-specific bumps is a candidate amendment after v2.0 baseline performance is evaluated.
- **Coach changes, system changes, and other roster turnover that is not transactional.** The model has no representation of who is playing or for whom.

### B. Design choices that bound the model's expressivity

These are choices the methodology made on purpose; they could be relaxed in a future amendment but doing so would change the model's character.

- **K-factor uniformity across playoff rounds.** §5 v1.1 fixes a single K_playoff for every playoff game. The grid search has no mechanism to vary K by round or series state.
- **Between-season decay as a single carry factor.** All franchises decay toward 1500 at the same rate. A team that lost its top scorer to free agency is decayed identically to a team that returns its core intact.
- **Uniform tie weight (0.50) for the pre-shootout era.** Fixed by §5 v1.1; not tunable. A regulation tie between a strong team and a weak team is weighted identically to a tie between two equal teams.
- **Symmetric outcome weights.** OUTCOME_WEIGHTS[REG_WIN] + OUTCOME_WEIGHTS[REG_LOSS] = 1, etc. The v1 grid did not explore asymmetric reward structures.
- **OT/SO outcome weights were not tuned.** v1 and v2.0 use the §5 starting values. Tuning them would expand the grid and is a pre-registered "future weight-tuning pass" rather than a v2.0 task.
- **`HOME_BUMP` is non-negative by construction.** Constrained to ≥ 0 in §12; a negative value is not considered defensible and is not represented in the grid.

### C. Empirical tensions between methodology and data

These are places where the data, when given freedom, prefers a configuration the methodology explicitly disallows or de-prioritizes. They are reported here rather than reconciled silently.

- **§5 K_playoff ≥ K_regular constraint vs empirical preference.** Both v1's 100-cell grid and v2.0's 600-cell grid consistently find their unconstrained log-loss minimum at K_playoff < K_regular (most often K_playoff = 6, K_regular ∈ {10, 12}). §5 pre-registers the opposite intuition ("playoff games receive a higher K because they are higher-information signals — teams are at full effort and the opponent pool is non-random"). Validation cost of enforcing the §5 constraint: ~0.0005 log-loss in v1, ~0.0002 in v2.0 — essentially within sampling noise. The methodology continues to enforce §5; the unconstrained winner is preserved in the frozen-params artifact for transparency. Possible explanations include (a) playoff games being noisier than §5 anticipates due to goalie hot streaks and small samples, (b) the validation window happening to contain unusually upset-heavy playoffs, or (c) a real signal that the §5 prior is wrong. We do not resolve this here.
- **Brier on test set lands inside the pre-registered band, but on the loose side.** v1's pre-registered Brier band was 0.235–0.245 (tightened from 0.250 in v1.1). v1 test Brier = 0.23921 — clearly inside, but closer to the floor than the ceiling. This is reported as a "model fits slightly better than expected" rather than a failure.

### D. Data-quality limitations

- **Pre-1967 NHL data is sparse, inconsistent, and incomplete.** The public `/v1/score` endpoint returns 0 games on many pre-expansion dates that historically had games scheduled. Pre-1942 in particular has limited coverage. §2, §3, and §4 explicitly exclude pre-1967 seasons from training, validation, and evaluation. No calibration claims are made for those seasons; their trajectories are exposed in the dashboard for historical exploration only.
- **PCHA / WHA / international / exhibition games appear under non-NHL team codes in the historical data.** The franchise lineage table (`franchises.py`) returns `None` for these codes; the engine drops the games. The count of dropped games is logged but not investigated case by case.
- **NHL API server errors on isolated old dates.** Some preseason dates in the 1980s return persistent HTTP 500. The pipeline treats post-retry 5xx as "empty day" rather than failing the whole season — a defensible choice for an open-ended ingest, but it means we can't distinguish "no games" from "data unavailable" in the source data.
- **One game in 2024-25 had a `gameState` of `FUT` with no period type at the time of ingest.** Excluded from rating updates. The pipeline is not idempotent against later state changes — re-ingesting overwrites cleanly, but a stale parquet would silently miss the update until the operator re-runs.

### E. Franchise-identity choices that involved judgment

These are §4 lineage decisions where the historical record is ambiguous and the codebase commits to one interpretation. They are listed so a future reviewer can audit them.

- **Hamilton Tigers (HAM, 1920-25) → New York Americans (NYA).** Treated here as the same franchise (sale/relocation). Some hockey historians argue the players were sold but the franchise was effectively dissolved and the Americans were a new franchise. Either reading is defensible; this codebase commits to the relocation interpretation.
- **California Golden Seals → Cleveland Barons → 1978 merger into Minnesota North Stars.** v1.2 specifies the simple-average merger rule — the absorbed franchise's pre-merger rating is averaged with the surviving franchise's at the season boundary. Three alternatives were considered (discard absorbed rating, transfer absorbed rating to surviving franchise, simple average) and the simple average was chosen as the most defensible reading of the v1.1 wording. None of the alternatives is mathematically wrong; the choice affects ~30 points of Dallas Stars rating across the immediate post-merger years.
- **Pittsburgh Pirates (PIR, 1925-30) → Philadelphia Quakers (QUA, 1930-31) → defunct.** Treated as a single franchise that relocated and then folded. Pre-1942 defunct franchises do not feed into any current-32 lineage.
- **Atlanta Flames (AFM) vs Atlanta Thrashers (ATL).** Two distinct franchises that happened to share a city and a name family at different times. The lineage table maps them to different franchise_ids (`calgary_flames` and `winnipeg_jets` respectively). This is the unambiguously correct treatment.
- **Toronto Arenas (TAN, 1917-19) → Toronto St. Patricks (TSP, 1919-27) → Toronto Maple Leafs (TOR, 1927+).** Single franchise, three names. No controversy; documented for completeness.
- **Detroit Cougars (DCG, 1926-30) → Detroit Falcons (DFL, 1930-32) → Detroit Red Wings (DET, 1932+).** Single franchise, three names. No controversy.

### F. v2.1 Cup-simulation approximations

These are specific to the Monte Carlo Cup sim layer (§14). They do not affect the rating model itself; they bound how faithfully the sim represents the playoff process built on top of the model.

- **Outcome-type sampling is rating-independent.** The sim draws REG / OT / SO outcomes from the 2024-25 league-wide distribution regardless of the rating gap between the two teams. In reality, evenly-matched games go to overtime more often than blowouts do; modeling overtime probability as a function of rating gap would be a more accurate approximation. The current approach is documented in §14 as the v2.1 starting point; refining it is v3 scope.
- **Conference membership is hardcoded.** `cup_simulator.EAST_TEAMS` and `cup_simulator.WEST_TEAMS` enumerate the current 32 franchises by conference. If the NHL realigns divisions, expands, or contracts, the literal sets in code must be updated. There is no test that detects future realignment automatically.
- **Higher-seed inference uses regular-season points only.** For not-yet-started series (e.g., the Conference Final before the Conference Semifinal winners are known), the Cup sim picks the higher seed by regular-season point total. NHL tiebreakers (regulation wins, head-to-head record, etc.) are not modeled. With current point spreads this rarely matters, but it's a known approximation.
- **Outcome distribution baseline is one season.** The 79 / 16 / 5 percent REG / OT / SO split uses 2024-25 only. Using a multi-season average would be a small refinement; the current choice was made to keep the dataset transparent.
- **No special handling for goalie injuries, suspensions, or back-to-back fatigue inside playoffs.** Series simulation treats each game as fresh — the sim has no concept of a starting goalie being unavailable for Game 6. This is consistent with the v1 / v2.0 rating model's scope (which also doesn't model these); flagged here because the playoff format makes the omission more visible.

### G. Methodology process limitations

- **Test sets shrink with each version.** v1's test was 2 seasons (2023-24 + 2024-25). v2's test is 1 season (2025-26). v3's test, if it follows the same pattern, will be ≤ 1 season. The shrinkage trades statistical power for the freshness of unseen data. A future amendment may need to address this — possibly by accepting wider confidence intervals on §6 metrics as test windows narrow.
- **One-shot test evaluation per §10 #1 means we cannot detect overfitting to the validation window.** If v2's validation choices happen to capture noise specific to 2021-22 → 2024-25, the test result will tell us, but only once and only via the held-out 2025-26 season. There is no cross-validation safety net.
- **No external comparison set.** §6 lists Vegas closing lines as "noted as context but not used as a success threshold." This is a deliberate choice — Vegas is a market, not a prediction model — but it means we have no independent calibrated reference to anchor our calibration plot against beyond the two naive baselines.

---

## Section 14 — v2.1 amendment: Monte Carlo Cup probabilities

**What v2.1 adds.** A new published quantity — for each team currently in the playoff field, the probability (per the model) that they win the 2026 Stanley Cup. Exposed via a new `/simulation/cup` endpoint. This is the second of four pre-registered v2 features; v2.0 added home-ice advantage, v2.2/v2.3 will add live in-game probabilities and hero-chart live updates.

**What v2.1 does NOT change.** The rating model is identical to v2.0. There are no new tunable parameters. The frozen v2.0 artifact (`frozen_params.json`) is the model used to drive the sim. Cup probabilities are a *forward projection* from current ratings, not a new model.

**Relation to §10 #1 (test-set quarantine).** The Cup sim uses the rating state as of "today," which is produced by replaying every season including 2025-26 to date. Replaying 2025-26 to produce ratings is not "examining test set results" — it's a state computation, the same one that powers `/games/today` and `/ratings/current`. The Cup sim never scores predicted probabilities against the actual outcomes of future 2025-26 games (because those outcomes do not yet exist), and never scores past 2025-26 games (which is what the v2 test evaluation will do, exactly once, after the Cup Final). The two surfaces — `/simulation/cup` (forward projection, free) and `/calibration/current` (held-out test evaluation, run once) — operate on different planes and do not interfere.

**Simulation algorithm.**

For each of `N_SIMS = 10,000` simulations:
1. **Start from current ratings.** A fresh copy of the rating state at "now" (after replaying everything in the parquet through 2025-26 to date).
2. **Continue any in-progress playoff series.** For each best-of-7 series where neither team has reached 4 wins, simulate one game at a time. The home team for each game follows the standard 2-2-1-1-1 home-away schedule based on the higher seed (derived from regular-season points). For each sampled game: compute `P(home wins) = win_probability(R_home, R_away, home_bump=HB)`, draw a uniform random number to decide the winner, then sample the outcome type (REG vs OT vs SO) from the historical 2024-25 distribution, then update both teams' ratings using the v2.0 rule. Continue until one team reaches 4 wins; the loser is eliminated.
3. **Propagate winners to the next round.** Build the next-round bracket by matching winners according to the actual NHL bracket structure (determined from the empirical Round 1 matchups, no need to re-derive seeding).
4. **Repeat steps 2-3 across all remaining rounds.** Conference Finals (best of 7), then Stanley Cup Final (best of 7).
5. **Record the Cup champion** for this simulation.

After all `N_SIMS` runs, `P(team wins Cup) = cup_count[team] / N_SIMS`. Confidence intervals at N=10,000 are roughly ±1% for the favorites.

**Sub-decisions and their rationale.**
- **Ratings update within a single sim run** (per user decision). Captures hot-streak dynamics. Alternative was static ratings; the v2.1 choice is closer to how playoffs actually unfold.
- **Outcome-type sampling from historical distribution.** Regular season + playoffs combined for 2024-25 produce roughly 79% regulation, 16% OT, 5% SO finishes. The sampled distribution does not change with team strength — a known approximation. (Refining this would require modeling overtime probability as a function of rating gap, which is v3 scope.)
- **No tiebreaker logic in standings.** The Cup field is already determined for 2025-26 (regular season is over). Tiebreakers would only matter for an in-progress regular season; that surface is deferred.
- **Coin-flip tiebreakers within a series are not needed** because best-of-7 cannot tie.
- **The simulation respects in-progress series.** If a series is currently 3-2, the sim only plays games 6 and 7 (if needed). It does not re-simulate games 1-5.

**Pre-registered expectations.**
- Cup probabilities should sum to exactly 1.0 across all teams currently in the playoff field (any team already eliminated has probability 0).
- The team with the highest current rating among playoff participants should have the highest Cup probability, but the gap to second place will be smaller than the rating gap suggests because four best-of-7 series introduce substantial variance.
- Repeated calls with the same input should produce slightly different numbers due to RNG, but the differences should be within the ±1% confidence interval at N=10,000.

**What is published, and what is honest about it.**
- Per-team Cup probability, rounded to 3 decimal places.
- The endpoint reports `n_simulations` and a `simulated_at` timestamp so the caller can judge freshness.
- The endpoint reports the current playoff state used as the starting point (eliminated teams, completed series, in-progress series, current round) — this is the audit trail.
- No comparison is made to published Cup probabilities elsewhere; like Vegas, those are markets, not predictions.

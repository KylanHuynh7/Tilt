# NHL Rating System — Methodology Document
## Version 1.1
**Author:** Kylan Huynh
**Status:** Pre-development — frozen before any code is written
**Last updated:** May 2026

**Amendment log:**
- *v1.1 (2026-05-17):* Six pre-code clarifications folded into the relevant sections before any implementation work. No model behavior is introduced that was not implied by v1.0; all changes resolve ambiguities flagged during a methodology review. Specifically: (1) expansion-team rating + decay interaction (Section 4), (2) franchise identity persistence across relocations (Section 4), (3) tie outcome weight for pre-2005-06 seasons (Section 5), (4) explicit uniform playoff K-factor across all rounds (Section 5), (5) `/games/today` frozen-parameter invariant (Sections 5 and 11), (6) Brier score upper bound tightened from 0.250 to 0.245 (Sections 2 and 6). See CHANGELOG.md for the corresponding commit.

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

**Franchise identity across relocations (v1.1 clarification):**
Franchise rating persists across relocations. When a franchise relocates, the new-city team inherits the prior-city team's most recent rating without any reset, and that rating continues to evolve under the same decay and update rules. Examples in the training and validation windows: Atlanta Flames → Calgary Flames (1980), Colorado Rockies → New Jersey Devils (1982), Minnesota North Stars → Dallas Stars (1993), Quebec Nordiques → Colorado Avalanche (1995), Hartford Whalers → Carolina Hurricanes (1997), Atlanta Thrashers → Winnipeg Jets (2011). The 1967 California Seals → Cleveland Barons → 1978 merger into the Minnesota North Stars is handled as relocation through the merger date and is then folded into the surviving franchise; pre-merger games count toward the surviving franchise's rating. This decision is for modeling simplicity and the absence of any defensible alternative that does not introduce arbitrary post-hoc choices; it is not a claim that relocated teams retain their old fans' team identity.

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

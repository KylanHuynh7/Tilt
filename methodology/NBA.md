# NBA Rating System — Methodology Document
## Version 1.1
**Author:** Kylan Huynh
**Status:** v1 rating model frozen and evaluated (2026-10-10): **all four §6 criteria PASS** on 2024-25 + 2025-26 (see §13). APPROVED 2026-10-10 — all seven **[DECISION]** items resolved as recommended. Implementation may begin. Any later change to §§3–6 or §12 is a version-tagged amendment.
**Last updated:** 2026-10-10

**Amendment log:**
- *v0.1-draft (2026-10-10):* First draft. Written after a data-availability probe and before any NBA ingest, rating code, or metric computation.
- *v1.0 (2026-10-10):* Author approved the draft with every [DECISION] resolved as recommended: (1) first season 1993-94, (2) test 2024-25 + 2025-26, (3) Charlotte lineage by roster continuity / ESPN ids, (4) MOV on/off in the grid, (5) no K_playoff ≥ K_regular constraint, (6) thresholds LL < 0.640, Brier 0.200–0.225, ECE < 0.04, must beat home-rate baseline, (7) three-term logistic live WP. No text below changed except this header.
- *v1.1 (2026-10-10):* Ingest-phase clarifications, made after ingest and before any rating code or metric. (a) **Data-validity rules** (§3): completed 0-0 games are dropped as impossible, and rows sharing (date, home, away) collapse to one game, keeping a valid score and then the lowest ESPN id. Raw parquets are untouched; the rules run on read and the manifest records every drop. (b) **Coverage outcome:** 1999-2000 fails the 1% rule (1,166 / 1,189 after cleaning), so under DECISION 1 the warm-up **starts in 2000-01**, not 1993-94. Every season from 2000-01 through 2025-26 passes. (c) Empty `{}` events in ESPN payloads are skipped; any other malformed event still raises. See §13.

---

> This document governs the NBA model the way `METHODOLOGY.md` governs the NHL model. It is a separate model with its own split, parameters, freeze, and one-shot test evaluation. Where this document says "inherits NHL §N", the NHL section applies verbatim with NBA seasons substituted. Where the two disagree, this document wins for NBA work.

### What was seen before this draft (contamination disclosure)

Pre-registration only means something if it says what the author had already looked at. Before writing this draft, the following NBA data was inspected — and nothing else:

- **Per-season game counts by season type** for 1990-91, 1993-94, 1995-96, 1996-97, 2001-02, and 2024-25, to establish coverage.
- **Which fields exist** in the ESPN scoreboard and summary payloads (period count, clock, scores, `neutralSite`, venue city, team ids), checked on roughly 20 individual dates.
- **About 25 individual matchup rows** (teams, team ids, venue, neutral flag — no scores) printed while checking those fields, plus **final scores for two games** (a 1995 WSH–BOS game and a 2025 playoff game's final play).

**No win rates, home-court rates, rating values, or metrics of any kind have been computed on NBA data.** General public knowledge of the NBA (e.g. that home-court advantage has declined since the 1990s) is the author's prior and is stated as such where used.

---

## Section 1 — Problem statement and scope

Build an interpretable team-rating system for the NBA that produces calibrated pre-game win probabilities, evaluated honestly against pre-registered targets, and surfaced on the same multi-sport dashboard as the NHL model.

**NBA v1 scope:**
- Game-by-game Elo ratings for every franchise from the first fully-covered season onward (§3).
- Pre-game win probability with **home-court advantage and a margin-of-victory update from day one.** The NHL model added home ice only in v2, after its v1 calibration plot showed the predictable miss; NBA starts with the lesson already learned.
- Calibration evaluation on a held-out test set touched exactly once.
- Dashboard: rating trajectories, today's games, calibration tab.

**NBA v1.1 scope (same freeze cycle, built after the rating model is frozen):** live in-game win probability (§12).

**Deferred to NBA v2 or later:** play-in + playoff bracket simulation (title odds), regular-season playoff-field projection, rest / back-to-back adjustments, player availability (injuries, load management), team- or era-specific home court.

Like the NHL model: not a betting tool, not a power ranking, not a Vegas competitor.

---

## Section 2 — Hypotheses and predictions

Written before any NBA model run.

**Expected to do well:** mid-season regular-season games between teams with clearly different ratings. Basketball is far less random than hockey per game (many more scoring events), so probabilities spread wider than in the NHL and the model should beat the naive baselines comfortably.

**Expected to do poorly:**
- *Early season* (roughly games 1–15). Carry-over ratings ignore offseason roster turnover, which in the NBA is concentrated in a few high-impact players.
- *Late regular season* (roughly the last 10 games per team). Resting starters, load management, and tanking by eliminated teams make results less tied to underlying strength. Expected to show as overconfidence on favorites who rest players and on teams playing out the string.
- *Games with star absences* at any point. A single player's availability moves NBA win probability more than in any other major sport, and the model cannot see it. This is expected to be the largest systematic error source.
- *Seasons with unusual home conditions:* the 2019-20 bubble and 2020-21 (limited or no fans).

**Pre-registered expectations for the test set:**
- Log-loss **< 0.640** (naive 50% = 0.693).
- Brier score **in 0.200–0.225.** Above 0.225 is a failure, reported as such.
- ECE **< 0.04.**
- The model beats the **home-rate baseline** (§6) on log-loss — i.e. ratings add information beyond "the home team usually wins."
- Tuned home-court bump in the **50–110 Elo** range. Outside 30–150 suggests a wiring bug.
- The margin-of-victory variant beats the binary-outcome variant on validation log-loss.

---

## Section 3 — Data sources, pipeline, and deployment

**Primary source: ESPN's public site API** (`site.api.espn.com/apis/site/v2/sports/basketball/nba/…`).
- `scoreboard?dates=YYYYMMDD` — one request per calendar day. Gives teams (with stable team ids), home/away, final score, period count (OT detection), season type, status, `neutralSite`, venue city. Date-range queries return nothing, so the ingest is strictly per-day (~270 requests per season).
- `summary?event={id}` — play-by-play with period, clock and running score. Available from at least 2002-03 (verified on 2002-03, 2004-05, 2006-07, 2008-09, 2010-11, 2012-13 samples); absent for 1999-2000.
- Live: the same scoreboard endpoint carries the in-progress period, clock and score, so live win probability needs no play-by-play fetch.

**Why not the official NBA sources:** `stats.nba.com` did not respond to scripted requests during the probe, and `cdn.nba.com`'s live JSON returned HTTP 403. Both are widely reported to block non-browser and cloud-hosted clients.

**Risks accepted with ESPN:** the API is undocumented and unofficial. It has no SLA, can change shape without notice, and its terms of use are not written for this purpose. The pipeline must fail loudly on schema changes. Whether it is reachable from the deployed backend (Render) is **unverified** until first deploy.

**Coverage.** Regular-season counts matched the schedule for 1993-94 (1,108 vs 1,107 expected), 1995-96 (1,189), 1996-97 (1,189), 2001-02 (1,191) and 2024-25 (1,239 incl. NBA Cup knockout games). 1990-91 returned playoff games only. **Rule:** a season enters the model only if its regular-season count is within 1% of the scheduled count. Every season is checked at ingest and the result recorded in the manifest. Seasons that fail are excluded and listed in §13; they are not patched from another source in v1.

**[DECISION 1] First modeled season.** Recommendation: **1993-94**, the earliest season verified complete. If any season between 1993-94 and the start of validation fails the coverage rule, the warm-up restarts from the first season after the gap, rather than bridging a hole in the record.

**Pipeline.** Mirrors NHL: idempotent per-season parquet at `backend/data_cache/nba/raw/{season}.parquet`, plus a manifest. Row schema: `game_id, season_id, game_date, season_type, home_team_id, away_team_id, home_score, away_score, n_periods, neutral_site, state`. Parquets are committed so the deployed backend boots without ingest (NHL §13.G).

**Game filter (pre-registered):**

| ESPN season type | Included? | K used |
|---|---|---|
| 1 preseason | no | — |
| 2 regular season (incl. NBA Cup group + knockout games) | yes | K_regular |
| 3 playoffs | yes | K_playoff |
| 5 play-in tournament | yes | K_playoff |
| All-Star / exhibitions vs non-NBA teams | no (team id not in lineage) | — |

NBA Cup knockout games are treated as regular-season games for rating purposes, even though the championship game does not count in league standings. They are competitive games between NBA teams, and the rating model cares about strength, not standings.

**Neutral sites.** A game is neutral if ESPN's `neutralSite` is true (verified true for the 2024 NBA Cup final in Las Vegas and the January 2025 Paris game) **or** its venue city is Lake Buena Vista, FL. ESPN does not flag the 2020 Orlando bubble games as neutral (verified on 2020-08-05 and 2020-10-09), so the city rule catches them. Venue *names* are not used: ESPN back-fills current arena names onto old games (e.g. "crypto.com Arena" for a 2000 Lakers game).

**Deployment.** Same backend process as NHL, routes under `/nba/*`. The historical cache is built lazily on first NBA request (§13.K of the NHL document).

---

## Section 4 — Train / validation / test split

- **Warm-up (training):** first modeled season (1993-94 per DECISION 1) through 2017-18. Predictions not recorded.
- **Validation (tuning only):** 2018-19 through 2023-24 (6 seasons, includes the bubble and 2020-21).
- **Test (held out, touched exactly once):** 2024-25 and 2025-26. Both are complete; the 2026 Finals ended in June 2026.
- **Live:** 2026-27 onward runs on frozen parameters (inherits NHL §5 v1.1 frozen-parameter invariant).

**[DECISION 2] Test window.** Recommendation: the two most recent complete seasons, as above. Two seasons give ~2,800 test predictions. One season would shrink power the way NHL §13.J warns about. Both seasons have already been played, but only their game counts have been examined (see the disclosure above).

**Between-season regression:** `R_new = 1500 + carry × (R − 1500)`, carry tuned (§5).

**Expansion and relocation:**
- Expansion franchises start at exactly 1500 with no regression in their first season (inherits NHL §4 v1.1). In-window expansions: Charlotte Bobcats (2004-05). (Toronto and Vancouver, 1995-96, fall before the v1.1 start.)
- Franchise identity follows **roster continuity**, keyed on ESPN's stable team id. ESPN already encodes this: the 1990s Charlotte Hornets share id 3 with New Orleans, the 2004 Bobcats/current Hornets are id 30, Vancouver and Memphis share id 29, Seattle and Oklahoma City share id 25.
- Relocations and renames inherit rating with no reset: Vancouver → Memphis (2001), Charlotte → New Orleans (2002, incl. the 2005-07 New Orleans/Oklahoma City interim), Seattle → Oklahoma City (2008), New Jersey → Brooklyn (2012), Bullets → Wizards (1997), Bobcats → Hornets (2014), New Orleans Hornets → Pelicans (2013).

**[DECISION 3] Charlotte lineage.** In 2014 the NBA officially reassigned the 1988–2002 Charlotte Hornets history to the current Charlotte franchise. Recommendation: **ignore the official reassignment and follow roster continuity** (ESPN's ids), for the same reason NHL §4 treats relocations by franchise continuity: the rating tracks the team on the floor, not the record book.

**First modeled season (resolved in v1.1): 2000-01.** Warm-up is 2000-01 → 2017-18 (18 seasons). The 1993-94 → 1999-2000 parquets stay on disk for audit but are never read by the model. The code enforces this (`pipeline.first_model_season()` derives it from the manifest).

**Shortened seasons:** 1998-99 (50 games, lockout), 2011-12 (66, lockout), 2019-20 (suspended, then bubble), 2020-21 (72). All included, no K adjustment, documented in §13 (inherits NHL §7 COVID handling).

---

## Section 5 — Model specification

**Initial conditions:** every franchise 1500 at the first modeled season. League mean fixed at 1500 by construction (zero-sum updates).

**Win probability** (via `app/core/elo.py`):

```
P(home wins) = 1 / (1 + 10 ^ ((R_away − R_home − H·h) / 400))
h = 0 for neutral-site games (§3), 1 otherwise
```

**Outcomes:** binary. Win = 1, loss = 0. No ties exist. Overtime gets no special weight: unlike hockey's OT/shootout, NBA overtime is ordinary basketball, and the margin-of-victory term already shrinks updates for close games.

**Rating update:**

```
R_new = R + K × M × (W − P)
```

**Margin-of-victory multiplier M** (FiveThirtyEight's NBA form, pre-registered rather than invented after seeing data):

```
M = (|MOV| + 3) ^ 0.8 / (7.5 + 0.006 × D)
D = (R_winner − R_loser), including the home bump on whichever side had it
```

The denominator damps updates when a favorite wins big, which keeps ratings from inflating through autocorrelation. Its constants (3, 0.8, 7.5, 0.006) are **fixed, not tuned.**

**[DECISION 4] MOV in the grid.** Recommendation: include an on/off switch in the grid (`mov ∈ {off, on}`, off ⇒ M = 1), so validation decides and the binary variant is reported either way.

**K-factors:** `K_regular` and `K_playoff` tuned independently.

**[DECISION 5] No K_playoff ≥ K_regular constraint.** NHL §5 imposed that constraint as a prior, and both NHL grids preferred the opposite (§13.C). Recommendation: **do not impose it for NBA.** Pre-register only the grid itself, and report the chosen relationship as a finding.

**Grid (validation, lowest log-loss wins, ties broken by ECE then Brier; inherits NHL rule):**

```
K_regular   ∈ {10, 15, 20, 25, 30}
K_playoff   ∈ {10, 15, 20, 25, 30}
carry       ∈ {0.55, 0.65, 0.75, 0.85}
H           ∈ {0, 40, 60, 80, 100, 120}
mov         ∈ {off, on}
```

1,200 cells. Ranges chosen from priors (FiveThirtyEight NBA Elo used K = 20, carry 0.75, H ≈ 100), not from NBA data.

**Frozen-parameter invariant:** inherits NHL §5 v1.1. `/nba/games/today` uses only the frozen artifact.

**Not in NBA v1:** player-level ratings, injuries / availability, rest days and back-to-backs, travel, team-specific home court, coaching changes, in-season trades, series context.

---

## Section 6 — Evaluation metrics with thresholds

Primary: **log-loss < 0.640.** Secondary: **Brier in 0.200–0.225**, **ECE < 0.04** (10 equal-width buckets, inherits NHL definition). All three reported for the model and every baseline, regardless of which is flattering (inherits NHL §10 #5).

**Baselines:**
1. Naive: 0.5 for every game.
2. **Home-rate:** the validation-period home win rate for every non-neutral game, 0.5 for neutral games. New for NBA. Home court is large enough that "the home team usually wins" is the honest floor, not 50%.
3. Static rating: end-of-warm-up ratings, frozen, with the tuned H (inherits NHL §6).

**Breakdowns emitted in the same one-shot evaluation pass.** The NHL v2 lesson (§13.C) was that a breakdown the evaluator does not produce cannot be added later without re-touching the test set. So the NBA evaluator must write all of these in its single run:
- per test season;
- regular season vs play-in + playoffs (flag in README if playoff ECE > 0.08, inherits NHL §8);
- team-game segments 1–15 / 16–65 / 66–82 (scaled for shortened seasons);
- neutral-site games;
- calibration buckets for each of the above with n per bucket.

**[DECISION 6] Thresholds.** Recommendation: as written. They are priors from published NBA Elo performance, not from this dataset. Tightening or loosening them after this document is approved would be an amendment.

---

## Section 7 — Backtest protocol

Inherits NHL §7 (walk-forward, predict-then-update, warm-up → validation → test, no look-ahead, regression applied once per franchise per season boundary).

---

## Section 8 — Failure modes

Inherits NHL §8, plus:
- **Home-court drift.** NHL v2 failed its test set largely because home advantage receded right after the validation window (NHL §13.C). If the NBA validation-window home rate trends strongly across 2018-19 → 2023-24, that is flagged *before* freezing. The response is to document it, not to add a time-varying term mid-cycle.
- **Late-season distortion.** If segment 66–82 ECE is more than double segment 16–65 ECE, report it as the pre-registered rest/tanking finding.
- **Rating inflation via MOV.** If the league mean drifts more than ±1 point from 1500 or any rating exits [1100, 1900] in warm-up, the MOV implementation is audited before proceeding.
- **Data source breakage.** If ESPN changes its schema mid-cycle, ingest fails loudly. No silent fallback to a different source within a freeze cycle.

---

## Section 9 — Stopping criteria (NBA v1)

1. This document approved by the author, all **[DECISION]** items resolved.
2. Ingest passes the coverage rule for every modeled season; the manifest records counts.
3. Every franchise rating stays in [1100, 1900] throughout the backtest.
4. Validation grid run, winner frozen to `backend/artifacts/nba/frozen_params.json` with the full grid preserved.
5. One-shot test evaluation run with every §6 breakdown, written to `backend/results/nba/test_evaluation.json`, numbers reported as-is.
6. Dashboard NBA tab: trajectories, today's games, calibration. NBA status flips to `live` in `/sports` and the frontend switcher.
7. CHANGELOG entries and §13 limitations written for each phase (standing project protocol).

---

## Section 10 — What I will not do

Inherits NHL §10 in full, with NBA test seasons (2024-25, 2025-26) substituted. Additionally:

- I will not use betting lines, ESPN's published win probabilities or predictor/BPI fields, or any third-party rating as a model input, tuning target, or success benchmark.
- I will not hand-correct individual game results. Data errors are documented, not patched, within a freeze cycle.

---

## Section 11 — Claude Code instructions

Inherits NHL §11, as modified by the author's standing override (Claude Code may commit and push; each phase ends with §13 limitations, a CHANGELOG entry, and a commit).

---

## Section 12 — NBA v1.1: live in-game win probability

Built only after the §5 rating model is frozen, because it uses the frozen pre-game probability as an input.

**[DECISION 7] Model form.** NHL v2.2 used a pure empirical lookup on (period, minute, score diff). For the NBA that is a poorer fit: score differences span roughly ±40 rather than ±5, so the bins get sparse fast, and team strength still matters late in close games. Recommendation, an interpretable three-term logistic model:

```
logit P(home wins | state) = β0 + β1 · pre · (τ / 2880) + β2 · d / sqrt(m + 1)

pre = logit of the frozen pre-game P(home wins)
τ   = seconds left in regulation (OT handled as its own short period with τ reset to 300)
m   = minutes remaining
d   = home score − away score
```

Interpretation: the pre-game edge fades linearly as time runs out, and a lead becomes more decisive as the time left shrinks. Three coefficients, all reportable.

- **Training data:** ESPN play-by-play, one sample per game-minute, for **2009-10 → 2017-18 only.** Warm-up seasons, so validation and test stay clean.
- **Evaluation:** once, on the test seasons, with log-loss / Brier / ECE by quarter, in the same spirit as §6.
- **Pre-registered checks:** at tip-off it reproduces the pre-game probability within 0.01; it is monotone in d; at any state with |d| ≥ 20 and m ≤ 2 it returns ≥ 0.97 for the leader.
- **Live:** `/nba/games/today` reads period, clock and score straight from the scoreboard. Polling 60 s, inheriting NHL §16 behavior and limitations.

---

## Section 13 — Known limitations (initial)

Written before any results exist; extended at every phase.

- **No player availability.** Star absences (injury, rest, suspension) are the largest single driver of NBA game outcomes the model cannot see.
- **No schedule context.** Back-to-backs, travel, and rest days are ignored.
- **Single league-wide home bump.** Ignores venue (altitude in Denver and Utah) and era drift. NHL v2's test failure is direct evidence this can break out of sample.
- **Expansion franchises start at 1500.** Toronto, Vancouver (1995-96) and Charlotte (2004-05) start at league average, which overstates them early. Zero-sum ratings make a below-mean seed deflate the league mean, so the NHL rule is kept for consistency.
- **Unofficial data source.** ESPN can change or withdraw the API. Coverage before 1993-94 is incomplete, so 1946-1993 history is not available in v1, unlike the NHL explorer's full history.
- **Bubble detection depends on venue city.** If ESPN ever back-fills a different city for those games, the neutral flag silently breaks; a test pins the expected count of bubble games.
- **NBA Cup knockout games are rated as regular-season games** even though the final doesn't count in standings.
- **Charlotte lineage follows ESPN team ids,** not the NBA's official 2014 record reassignment (DECISION 3).
- **ESPN carries phantom and duplicate rows** (found at ingest). 1999-2000 has 82 completed 0-0 "finals", 76 of them regular-season Chicago games, each shadowing a real game under a 400-series id. Single 0-0 phantoms appear in 2000-01 and 2001-02, and exact same-day duplicates in 2002-03, 2005-06, 2007-08 (×2) and 2025-26. Handled by the v1.1 validity rules. A phantom with a *non-zero* fake score, on a different date from the real game, would not be caught; per-team game counts (82 for every team in every passing season, except NBA Cup finalists at 83) are the evidence that none exist.
- **1990s history is unavailable.** 1999-2000 is missing 23 real regular-season games in ESPN's data, which fails the coverage rule and moves the start to 2000-01. Six otherwise-complete seasons (1993-94 → 1998-99) are discarded rather than bridged, per DECISION 1. Expansion rules for the 1995 Raptors and Grizzlies therefore never apply. All 29 franchises existing in 2000-01 start at 1500 together, and only the 2004-05 Bobcats are a true in-window expansion.
- **2012-13 has 1,229 regular-season games, not 1,230.** The Celtics–Pacers game cancelled after the Boston Marathon bombing was never played. Within the 1% rule; noted so the count isn't mistaken for a gap.
- **Frozen parameters (N3, 2026-10-10):** `K_regular = 15`, `K_playoff = 10`, `carry = 0.65`, `H = 40`, `mov = on`, from the 1,200-cell grid on 2018-19 → 2023-24. Validation (n = 7,588): LL 0.63072, Brier 0.22038, ECE 0.01274. Baselines on the same games: naive LL 0.69315; home-rate (54.7–59.0% by season, pooled constant) LL 0.68573; static rating LL 0.75380. These are validation numbers, not claims; only the one-shot test pass counts (§10 #6).
- **Pre-registration miss: home bump.** §2 expected H in 50–110; validation chose **40**. It sits outside the 30–150 wiring-bug range, and log-loss traces a clean U across the grid (H = 0: 0.63925, 40: 0.63072, 60: 0.63099, 80: 0.63421, 100: 0.64028, 120: 0.64912), so it is not a bug. The prior was anchored on older FiveThirtyEight work from an era with a ~60% home win rate. A validation-era rate near 56% implies roughly 42 Elo for evenly matched teams. Reported as a missed expectation, not re-specified. The grid is coarse between 40 and 60, which nearly tie (Δ LL 0.00027).
- **K_playoff came out lower than K_regular** (10 vs 15), the same direction as the NHL grids (NHL §13.C). K_playoff = 10 is the bottom of the grid, so the optimum may lie lower. The best cell honoring K_playoff ≥ K_regular is 0.00007 LL worse, which is noise. No constraint was imposed (DECISION 5).
- **MOV helped as pre-registered,** but modestly: best MOV-off cell LL 0.63350 vs 0.63072.
- **Home-court rate by validation season** (non-neutral games): 2018-19 59.0%, 2019-20 55.3%, 2020-21 54.7%, 2021-22 54.8%, 2022-23 58.2%, 2023-24 54.7%. There is no monotone trend, so the §8 drift check does not flag. But the year-to-year swing (±2 pts) is the same size as the home-ice drop that sank NHL v2, and a single H = 40 cannot follow it.
- **The static-rating baseline is far worse than naive on validation** (LL 0.754). It holds end-of-2017-18 ratings for six seasons, so it mainly measures how fast NBA team strength turns over, not a model defect.
- **Test evaluation (N4, run once 2026-10-10, `results/nba/test_evaluation.json`):** 2024-25 + 2025-26, n = 2,643. Model **LL 0.60744 (PASS < 0.640), Brier 0.20991 (PASS 0.200–0.225), ECE 0.02590 (PASS < 0.04)**, and it beats the home-rate baseline (LL 0.68834) — **all four §6 criteria pass.** Naive LL 0.69315; static rating (frozen end of 2023-24) LL 0.70867. Locked per §10 #2.
  - *Per season:* 2024-25 ECE 0.0155; **2025-26 ECE 0.0419**, which would miss the 0.04 target on its own. The pooled pass leans on 2024-25.
  - *Postseason (play-in + playoffs, n = 181):* LL 0.65136, ECE 0.0549. Below the 0.08 flag, but clearly worse than the regular season (ECE 0.0312), as §2 expected.
  - *§8 late-season flag fired.* Late-segment ECE 0.0855 is 2.85× mid-segment (0.0300). **The direction contradicts §2's mechanism.** §2 predicted overconfidence from favorites resting starters. Instead the model is *underconfident* late: favorites at 0.55 / 0.65 / 0.75 won 0.64 / 0.75 / 0.86, and underdogs at 0.26 / 0.35 won 0.18 / 0.21. That fits tanking (weak teams losing more than their rating implies) better than rest. Late-segment LL (0.543) is the best of the three segments, because outcomes there are *more* predictable than the model says.
  - *Early segment:* ECE 0.0463, also above target; the 0.7–0.8 bucket won 0.877 vs 0.746 predicted (n = 73).
  - *Heavy home underdogs:* the 0.1–0.2 bucket (n = 51) predicted 0.168 and won 0.039.
  - *Neutral-site games:* n = 12 (NBA Cup knockouts, international games). ECE 0.31 is noise at that size; reported only for completeness.
- **Dashboard / API (N5):**
  - *ESPN reachability from Render is still unverified.* `/nba/games/today` calls ESPN on every request (no caching) and returns 502 if it's unreachable; history and calibration don't depend on ESPN at request time.
  - *Champion = winner of the season's last playoff game.* That is the Finals clincher in every modeled season (it reproduces MIL 2021, GSW 2022, DEN 2023, BOS 2024, OKC 2025). Not shown for the in-progress season.
  - *Preseason games are omitted from "Today's games"* rather than shown without a probability. Early October therefore looks empty.
  - *No live win probability yet.* Live games show score and clock only, until v1.1 (§12).
  - *Display colors substitute for dark primaries* (e.g. Spurs and Nets lines use silver/grey, Bucks cream, Nuggets gold), the same coupling as NHL §13.I.
  - *`/nba/admin/refresh` is unauthenticated and its ingest is ephemeral* on free hosting, inheriting NHL §13.G.
- *Rating engine (N2):* no limitations beyond those §5 already lists. One display detail: each team's season trajectory opens at its first game's date, carrying the post-regression rating.
- **No logos.** Team identity uses colored badges, inheriting NHL §13.I trademark reasoning.

---

## Decisions (resolved 2026-10-10 — all as recommended)

| # | Decision | Recommendation |
|---|---|---|
| 1 | First modeled season | 1993-94, the first verified-complete season |
| 2 | Test window | 2024-25 + 2025-26 |
| 3 | Charlotte lineage | Roster continuity (ESPN ids), not the NBA's 2014 reassignment |
| 4 | Margin of victory | In the grid as on/off |
| 5 | K_playoff ≥ K_regular constraint | Do not impose |
| 6 | §6 thresholds | LL < 0.640, Brier 0.200–0.225, ECE < 0.04, must beat home-rate baseline |
| 7 | Live WP form | Three-term logistic using the frozen pre-game probability |

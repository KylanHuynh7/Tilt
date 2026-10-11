# College Football (FBS) Rating System — Methodology Document
## Version 1.2
**Author:** Kylan Huynh
**Status:** v1 frozen and evaluated 2026-10-11 — **all four §6 criteria PASS** on 2022–2025 (postseason flagged). APPROVED 2026-10-11 — all six **[DECISION]** items resolved as recommended. Later changes to §§3–6 or §12 are version-tagged amendments.
**Last updated:** 2026-10-11

**Amendment log:**
- *v0.1-draft (2026-10-11):* First draft, after a data-availability probe and before any ingest, rating code or metric.
- *v1.0 (2026-10-11):* Author approved with every [DECISION] as recommended: (1) ESPN source, (2) pooled FCS rating with FBS-vs-FCS games excluded from metrics, (3) new FBS programs start at the pooled FCS rating, (4) no K_post ≥ K_regular constraint, (5) thresholds as written, (6) live targets inherit NFL's.
- *v1.1 (2026-10-11):* Ingest-phase clarifications, made before any rating code or metric.
  - **(a) FBS membership.** ESPN's group-80 list contains never-playing placeholder ids (it shows 145 teams in a 133-team 2023) and omits teams in some early seasons. The rule is now: in ESPN's group-80 list **and** played ≥ 1 completed game, **or** played ≥ 6 completed games against ESPN-listed FBS opponents. That reproduces the official FBS counts exactly (117 in 2001 … 136 in 2025).
  - **(b) Season type and week come from each event, not the query.** ESPN's `seasontype=3` query returned ~390 regular-season games per pre-2024 season.
  - **(c) Bowls and playoff** are fetched by date (Dec 1 → Jan 20), keeping events ESPN marks as postseason. Week-based queries never returned pre-2024 bowls. Regular-season weeks run through week 17.
  - **(d) Coverage rule** counts regular-season games *listed* (completed, or cancelled/postponed) and requires ≥ 11, not "12 from 2006". The rule exists to detect missing data, not unplayed games: the 9/11 week (2001) and hurricanes Harvey and Irma (2017) cancelled real games, and 12-game schedules were optional from 2006. With (a)–(d) every season 2001–2025 passes; 2020 is exempt.
  - **(e)** Games with no FBS team (FCS playoff games returned by date queries) are dropped.
- *v1.2 (2026-10-11):* Pooled-FCS details, fixed before any backtest ran. §5 calls the FCS rating's per-season regression "tuned", but the approved grid has no separate parameter for it. Resolution: the pooled FCS rating regresses toward its own starting value `fcs_init` using the **same `carry`** as FBS teams, which adds no new tuned dimension. A program that leaves FBS (e.g. Idaho after 2017) drops out of the FBS state and is represented by the pool. Teams already FBS in 2001 start at 1500. A program entering FBS starts at the pool's current value (DECISION 3).

---

> A separate model with its own split, parameters, freeze and one-shot evaluation, inheriting the NFL document (`methodology/NFL.md`) where stated. Scope is **FBS** (the top division). FCS teams appear only as opponents (DECISION 2).

### What was seen before this draft (contamination disclosure)

- **ESPN college-football scoreboard:**
  - game counts for week 5 of 1995 (0), 2000 (0), and 2001–2005, 2015, 2024 (51–60 each);
  - full-season counts for 2010 (845 games, 221 teams, 120 with ≥ 12 games, 76 with ≤ 2 games, 40 neutral) and 2023 (896 games, 238 teams, 133 with ≥ 12 games, 98 with ≤ 2 games, 32 neutral);
  - the 2024 postseason count (46 games, 41 neutral);
  - field names, and one matchup row per probed week (team codes only).
  - **No scores, results or win rates.**
- **Author's priors (public knowledge):**
  - college home-field advantage is larger than the NFL's (≈ 2.5–3.5 points);
  - FBS-vs-FCS games are lopsided;
  - roster turnover between seasons is large (graduation, NFL draft, transfer portal);
  - the playoff expanded from 4 to 12 teams in 2024.

---

## Section 1 — Scope

- **CFB v1:** game-level win probabilities for FBS games from a team Elo with home field and margin of victory; one-shot calibration; dashboard (trajectories, this week's games, calibration, game-detail pages with rosters and player cards from ESPN), in a new college-football color world.
- **CFB v1.1 (after v1 freezes):** live in-game win probability (§12).
- **Deferred:** recruiting rankings, returning production, transfer-portal adjustments, QB adjustment, playoff/bowl simulation, conference strength priors.

---

## Section 2 — Hypotheses and predictions

- **More predictable per game than the NFL**, because FBS talent gaps are wide (powerhouses vs. small-conference programs).
- **Expected to do poorly:**
  - *Weeks 1–4,* when carry-over ratings meet a heavily turned-over roster; this should be the worst segment by a wide margin;
  - *bowl games* (opt-outs, coaching changes, long layoffs);
  - *the first expanded-playoff seasons* (2024–25);
  - *teams in their first FBS seasons.*
- **Late regular season:** direction not predicted; flagged if late ECE > 2× mid.

**Pre-registered expectations (test, FBS-vs-FBS games):**
- **Log-loss < 0.600; Brier 0.170–0.210; ECE < 0.04.**
- **Beats the home-rate baseline on LL.**
- **Home bump 40–100 Elo;** outside 0–160 means a wiring bug.
- **MOV beats binary outcomes on validation.**

---

## Section 3 — Data

**Source: ESPN college-football scoreboard** (same client pattern as NBA / NFL live data): `scoreboard?dates=YYYY&week=N&groups=80` for weeks 1–16, plus `seasontype=3` for the postseason. That's about 17 requests per season. The response carries teams (stable ESPN ids), scores, `neutralSite`, `conferenceCompetition`, status and week. ESPN `odds`, predictor and FPI fields are **never read** (§10).

**Coverage:** data starts in **2001** (2000 returns nothing).

**Coverage rule (§3, clarified in v1.1):** a season enters only if at least 95% of FBS teams have ≥ 11 regular-season games listed (completed or cancelled/postponed). **2020** (COVID: cancellations, conference-only schedules) is exempt from the game-count part and flagged.

**[DECISION 1] Alternative source.** CollegeFootballData.com has deeper history (1869+) but needs a personal API key, and it also exposes betting lines and its own ratings (never to be read). Recommendation: **ESPN for v1** (no key, same client as the other sports, coverage from 2001 is enough). CFBD is a fallback if ESPN coverage proves patchy.

**Who is FBS:** determined per season from ESPN's FBS group membership at ingest, recorded in the manifest. A team is FBS in a season if it belongs to group 80 that season.

---

## Section 4 — Split

- **Warm-up:** 2001 → 2013.
- **Validation:** 2014 → 2021 (includes 2020).
- **Test (touched once):** 2022, 2023, 2024, 2025. All complete; the 2025 season ended with the January 2026 playoff final. About 2,900 FBS-vs-FBS games.
- **Live:** 2026 on frozen parameters (the 2026 season is in progress now).

**Regression:** each season boundary regresses toward the mean; carry is tuned (expected well below the NFL's, given turnover).

**Lineage:** ESPN team ids are stable. Programs that join FBS (e.g. Sam Houston and Jacksonville State in 2023, Kennesaw State in 2024, Delaware and Missouri State in 2025) are handled by DECISION 3.

---

## Section 5 — Model

Inherits the NFL §5 Elo form exactly: neutral-aware home bump, W ∈ {1, 0.5, 0}, FiveThirtyEight NFL MOV multiplier with ties at M = 1.

**[DECISION 2] FCS opponents.** FCS teams play FBS teams one to three times a season, which is far too few games to rate individually. Recommendation: **all FCS teams share one pooled "FCS" rating**, updated by every FBS-vs-FCS game like a normal team. Its starting value and its per-season regression are tuned (`fcs_init ∈ {1100, 1200, 1300}`). **FBS-vs-FCS games update ratings but are excluded from every reported metric**: they are near-certain wins and would make calibration look better than it is. Their results are reported separately for transparency.

**[DECISION 3] New FBS programs.** Recommendation: a team moving up from FCS starts at the **current pooled FCS rating**, not 1500. It was an FCS program the week before.

**[DECISION 4] K_playoff ≥ K_regular.** Recommendation: don't impose it. Bowls and the playoff are a handful of games per team; the grid decides.

**Grid:**

```
K_regular ∈ {20, 30, 40, 50}
K_post    ∈ {10, 20, 30, 40}           (bowls + playoff)
carry     ∈ {0.40, 0.50, 0.60, 0.70}
H         ∈ {0, 40, 60, 80, 100, 120}
mov       ∈ {off, on}
fcs_init  ∈ {1100, 1200, 1300}
```

2,304 cells.

**Not in v1:** recruiting, returning production, transfers, QB, coaching changes, conference priors.

---

## Section 6 — Evaluation

On **FBS-vs-FBS games only**:
- Primary **LL < 0.600**; **Brier 0.170–0.210**; **ECE < 0.04**; **beat the home-rate baseline**.
- Baselines: naive, home-rate, static rating.

**One-pass breakdowns (inherits NFL):**
- per season;
- regular season vs bowls/playoff;
- weeks 1–4 / 5–10 / 11+;
- neutral site;
- conference vs non-conference;
- calibration buckets for each.

FBS-vs-FCS games are reported separately, never pooled.

**[DECISION 5] Thresholds.** Recommendation as written.

## Sections 7–11

Inherit NFL §§7–11 with CFB test seasons substituted. §10 adds: no betting lines, no ESPN FPI or predictor fields, no CFBD ratings, and no polls or rankings as inputs.

---

## Section 12 — CFB v1.1: live win probability

Inherits the NFL §12 five-term form (pre-game edge fading over time, score margin, possession, field position), refitted on college data, since college clock rules and scoring rates differ.
- **Training:** ESPN college play-by-play for warm-up seasons (2014-era coverage to be verified at ingest; recorded in a pre-download amendment, as for MLB v1.2).
- **Evaluation:** once on 2022–2025.

**[DECISION 6] Live targets:** inherit NFL's (beat the pre-game-held baseline every quarter, ECE < 0.05, three structural checks).

---

## Section 13 — Known limitations (initial)

- **No preseason talent signal.** Recruiting, returning production and transfers are not modeled, so early-season predictions lean on last year's regressed rating while rosters change heavily.
- **FCS opponents are one pooled rating,** so a strong FCS program is treated like a weak one.
- **Huge schedule imbalance:** teams rarely play outside their conference, so cross-conference strength is inferred from few games (mostly September non-conference games and bowls).
- **Bowl games** include opt-outs and interim coaches the model can't see.
- **The playoff format changed** (4 → 12 teams in 2024), inside the test window.
- **Coverage starts in 2001;** earlier history isn't available from this source.
- **Frozen parameters (N3, 2026-10-11):** `K_regular 40, K_post 40, carry 0.70, H 40, mov on, fcs_init 1300`, from the 2,304-cell grid on 2014–2021 (FBS-vs-FBS games, n = 5,911). Validation LL 0.54555, Brier 0.18492, ECE 0.02135. Baselines: naive 0.69315, home-rate 0.68105, static 0.78757.
  - *H = 40 sits exactly on the lower edge of the pre-registered 40–100.*
  - *MOV matters far more here than in any other sport:* best MOV-off cell LL 0.56669 (+0.021).
  - *K_post = K_regular in the winner,* so DECISION 4 never came into play.
  - *`fcs_init` = 1300 is the top of its grid,* but the pool falls to 1062 by 2021, below every FBS program.
  - *Home rate by validation season* is 56.4 → 60.3% across 2014–2019, then 56.7% (2020) and 58.5% (2021). It rose rather than fell; no downward-drift flag, but noted.
- **§8 failure modes fired at freeze, then audited, no bug found.**
  - *Rating range:* FBS ratings at the end of validation span 908 (UMass) to 2044 (Georgia), outside the inherited [1100, 1900] band.
  - *League mean:* the FBS mean is 1492.2, outside the inherited ±1 of 1500, because rating points move to and from the pooled FCS rating and entrants start at the pool value.
  - *Audit, as §8 requires before proceeding:* (1) the MOV multiplier matches the approved formula exactly; (2) the extremes are the right programs (Georgia, Alabama, Cincinnati and Ohio State on top; UMass, UConn, FIU and New Mexico State at the bottom); (3) extreme predictions are calibrated (validation 0.9–1.0 bucket: predicted 0.939, won 0.959; 0.0–0.1: predicted 0.069, won 0.078).
  - *Conclusion:* the bands, inherited from leagues with far less talent dispersion, don't fit FBS. Reported as a finding; parameters unchanged.
- **Test evaluation (N4, run once 2026-10-11, `results/cfb/test_evaluation.json`):** 2022–2025, FBS-vs-FBS games, n = 3,174. **LL 0.57072 (PASS < 0.600), Brier 0.19461 (PASS 0.170–0.210), ECE 0.02450 (PASS < 0.04)**, and it beats the home-rate baseline (0.67842). **All four §6 criteria pass.** Naive 0.69315; static 0.79033. Locked per §10 #2.
  - ***Postseason flag fired:*** bowls + playoff n = 176, LL 0.68453 (barely below the coin flip), ECE **0.0906**. Neutral-site games (mostly bowls) are similar: LL 0.667, ECE 0.098. Reported as a weakness; consistent with opt-outs, interim coaches and long layoffs (§2).
  - ***Pre-registration miss:*** §2 expected weeks 1–4 to be the worst segment by a wide margin. They are better than mid-season (LL 0.558 vs 0.584; ECE 0.033 vs 0.042). Late season is best (LL 0.540, ECE 0.030). Late-season flag not fired (ratio 0.72).
  - *Per season:* ECE 0.037 / 0.035 / **0.040 / 0.043** (2022–2025). The two expanded-playoff seasons sit at or just over the target individually.
  - *Conference vs non-conference:* ECE 0.022 vs 0.036.
  - *FBS-vs-FCS games, reported separately as agreed (never pooled):* n = 485, FBS teams won 95.5%, LL 0.169.
- **Dashboard / API (N5):**
  - *Trajectory chart shows only each season's top 25 at season's end plus the champion,* because 130+ lines are unreadable. Teams outside the top 25 are still rated and served; they just aren't drawn.
  - *Champion = winner of the season's last postseason game* (BCS / CFP final). Reproduces Alabama 2020, Georgia 2021–22, Michigan 2023, Ohio State 2024.
  - *Team colors* are ESPN's, with near-black primaries swapped for the alternate (or a neutral grey) on the dark UI.
  - *Game pages* use ESPN rosters with injury status. ESPN publishes **no college depth charts**, so players are grouped by position with a note.
  - *Player cards* use ESPN college stats. Players with none recorded (often freshmen) show an empty card rather than an error.
  - *FCS opponents* show the pooled FCS rating, and their games carry no track-record figure (those games were excluded from evaluation).
  - *No live win probability yet* (v1.1).
- **No logos:** inherits NHL §13.I. Headshots follow the author's ESPN-headshot decision (§13.I).

---

## Decisions (resolved 2026-10-11 — all as recommended)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Data source | ESPN (no key; from 2001); CFBD only as a fallback |
| 2 | FCS opponents | One pooled FCS rating (start value tuned); FBS-vs-FCS games update ratings but are excluded from metrics |
| 3 | New FBS programs | Start at the current pooled FCS rating |
| 4 | K_post ≥ K_regular | Do not impose |
| 5 | Thresholds | LL < 0.600, Brier 0.170–0.210, ECE < 0.04, beat home-rate (FBS-vs-FBS only) |
| 6 | Live targets | Inherit NFL's |

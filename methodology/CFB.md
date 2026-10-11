# College Football (FBS) Rating System — Methodology Document
## Version 0.1-draft
**Author:** Kylan Huynh
**Status:** DRAFT — pre-code. **No college football model code may be written until the author approves this document.** Items marked **[DECISION]** need an explicit ruling; each carries a recommendation.
**Last updated:** 2026-10-11

**Amendment log:**
- *v0.1-draft (2026-10-11):* First draft, after a data-availability probe and before any ingest, rating code or metric.

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

**Coverage rule (§3):** a season enters only if at least 95% of FBS teams (teams with ≥ 10 games that season) have their full regular season recorded (≥ 11 games, ≥ 12 from 2006). **2020** (COVID: cancellations, conference-only schedules) is exempt from the game-count part and flagged.

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
- **No logos:** inherits NHL §13.I. Headshots follow the author's ESPN-headshot decision (§13.I).

---

## Decisions needed before implementation

| # | Decision | Recommendation |
|---|---|---|
| 1 | Data source | ESPN (no key; from 2001); CFBD only as a fallback |
| 2 | FCS opponents | One pooled FCS rating (start value tuned); FBS-vs-FCS games update ratings but are excluded from metrics |
| 3 | New FBS programs | Start at the current pooled FCS rating |
| 4 | K_post ≥ K_regular | Do not impose |
| 5 | Thresholds | LL < 0.600, Brier 0.170–0.210, ECE < 0.04, beat home-rate (FBS-vs-FBS only) |
| 6 | Live targets | Inherit NFL's |

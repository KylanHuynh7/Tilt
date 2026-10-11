# MLB Rating System — Methodology Document
## Version 1.1
**Author:** Kylan Huynh
**Status:** APPROVED 2026-10-11 — all six **[DECISION]** items resolved as recommended. Later changes to §§3–6 or §12 are version-tagged amendments.
**Last updated:** 2026-10-11

**Amendment log:**
- *v0.1-draft (2026-10-11):* First draft, after a data-availability probe and before any MLB ingest, rating code, or metric.
- *v1.0 (2026-10-11):* Author approved with every [DECISION] as recommended: (1) test 2022–2025, (2) MOV on/off, (3) starting-pitcher adjustment in v1, (4) no K_playoff ≥ K_regular constraint, (5) thresholds LL < 0.685, Brier 0.235–0.248, ECE < 0.03, beat home-rate, (6) v1.1 live targets as in §12.
- *v1.1 (2026-10-11):* Ingest-phase validity rule, made before any rating code or metric. A game counts only if it is final **and** has both scores: the API lists some games as final with no score (35 in 2000). Same-day, same-teams pairs are **not** collapsed, because in MLB they are real doubleheaders (unlike the NBA v1.1 duplicate rule). With the rule applied, 2000 has 2,429 of 2,430 regular-season games and passes coverage. Pitcher-term details, also fixed before any rating code ran: (i) a team's `rGS_t` starts at the league's running mean game score up to that game (50.0 before the first game), with no look-ahead; (ii) pitcher `rGS_p` and team `rGS_t` carry over between seasons unchanged, and only Elo regresses; (iii) after every game both the actual starter's `rGS_p` and the team's `rGS_t` update with that start's game score, using the same α; (iv) when the 2010+ probable pitcher is missing, the actual starter is used; (v) the 2000 phantom rows have boxscores fetched, but they never enter the model because they fail the validity rule.

---

> A separate model with its own split, parameters, freeze and one-shot evaluation, inheriting the NBA / NFL documents where stated.

### What was seen before this draft (contamination disclosure)

- **MLB Stats API `schedule`:** field names; per-season counts of rows, finals, postponements and ties for 1990, 2000, 2010, 2015, 2020, 2024, 2025; how many finals list a probable pitcher for both teams. One 1985 and one 2024 row (team name, game type, status, venue, probable pitcher name). **No scores, results or win rates.**
- **Author's priors (public knowledge):**
  - MLB single games are close to coin flips; even strong favorites rarely exceed ~65%.
  - Home-field advantage is ~53–54%.
  - The starting pitcher is the largest single-game factor.
  - FiveThirtyEight's MLB Elo used a rolling starting-pitcher adjustment.

---

## Section 1 — Scope

- **MLB v1:** game-level win probabilities from team Elo with home field and (per DECISION 3) a starting-pitcher adjustment; one-shot calibration evaluation; dashboard (trajectories, today's games, calibration, game-detail pages). It uses the MLB "ballpark night" world already styled.
- **MLB v1.1 (after v1 freezes):** live in-game win probability (§12).
- **Deferred:** postseason bracket simulation, bullpen fatigue, lineups / platoons, weather, park factors beyond home field.

---

## Section 2 — Hypotheses and predictions

- MLB is the least predictable of the four sports per game. Expect log-loss only modestly below the coin flip.
- **Team-only Elo** (if DECISION 3 rejects the pitcher term) is expected to land within ~0.01 LL of the home-rate baseline. **With the pitcher adjustment** the gap should be clearly larger.
- **Expected to do poorly:** opener / bullpen games (the "starter" pitches one inning), September call-up games, the shortened 2020 season, and games right after trades.
- **Late season:** direction not predicted; flagged if late-segment ECE > 2× mid (inherits NFL §2).

**Pre-registered expectations (test):**
- **Log-loss < 0.685** (naive 0.693).
- **Brier 0.235–0.248.**
- **ECE < 0.03.** The bound is tighter than other sports because ~9,800 test games make 10-bucket ECE noise ~±0.01.
- **Beats the home-rate baseline on LL.**
- **Home bump 15–40 Elo** (≈ 52–56% for equal teams); outside 0–80 means a wiring bug.

---

## Section 3 — Data

**Source: MLB Stats API** (`statsapi.mlb.com/api/v1`), the official free API. Its terms permit individual, non-commercial use with attribution ("Data courtesy of MLB Advanced Media"); Tilt is a non-commercial student project, and the attribution will be shown on MLB pages.
- `schedule?sportId=1&season=Y&gameType=R|F|D|L|W&hydrate=probablePitcher`: one request per season and game type. It returns every game with teams, venue, status, scores, and the announced probable pitchers from 2010 onward.
- `game/{gamePk}/boxscore`: starting pitchers' lines (IP, H, ER, BB, K, HR) for the pitcher adjustment (DECISION 3).
- `game/{gamePk}/feed/live` (v1.1 only): inning, half, outs, runners, score. Only state fields are read. Win-probability or odds fields, if present, are never read (§10).

**Coverage rule:** a season is included only if its completed regular-season games (after collapsing suspended-and-resumed duplicates) are within 1% of the schedule:
- 26 teams × 162 / 2 = 2,106 through 1992;
- 28 teams from 1993;
- 30 teams from 1998;
- 2,430 thereafter, except the 1994–95 strike seasons and 2020 (60 games, 900).

Unplayed postponements that were never made up are allowed within the 1%.

**Game filter:** regular season at K_regular; Wild Card / Division / LCS / World Series at K_playoff; spring training and exhibitions excluded. Ties (rare, pre-2020) count as W = 0.5. Neutral sites (London, Seoul, Mexico City, Tokyo, the Field of Dreams game, etc.) get no home bump, identified by the venue's home team not matching either team. The exact rule is fixed at ingest and recorded.

**Lineage:** the Montreal Expos (MON) became the Washington Nationals (WSN) in 2005; the franchise continues. Renames (Indians → Guardians, Devil Rays → Rays, Angels variants) are the same franchise. The Oakland Athletics' 2025 move to Sacramento (and planned Las Vegas move) is the same franchise. The 1998 expansion teams (Arizona, Tampa Bay) are seeded at 1500 if they fall in the modeled window.

---

## Section 4 — Split

- **Warm-up:** 2000 → 2014.
- **Validation:** 2015 → 2021 (includes 2020).
- **Test (touched once):** 2022, 2023, 2024, 2025 — all complete, ~9,800 games incl. postseason.
- **Live:** 2026 on frozen parameters (2026 postseason is in progress now).

**[DECISION 1] Test window.** Recommendation: 2022–2025, matching NFL. MLB has 4× the games per season, so this also gives the most precise test of any sport. It spans the 2023 pitch-clock / shift-ban rule changes, which is a real test of robustness.

---

## Section 5 — Model

```
P(home wins) = 1 / (1 + 10 ^ ((R_away + A_away − R_home − A_home − H·h) / 400))
R_new        = R + K × M × (W − P)
```

**Margin of victory:** run differential, FiveThirtyEight-style multiplier with fixed constants, `M = ln(|MOV| + 1) × 2.2 / (0.001 × D + 2.2)`.

**[DECISION 2] MOV in the grid.** Recommendation: on/off, as NBA and NFL. MOV may matter less in baseball (blowouts are partly bullpen noise); validation decides.

**[DECISION 3] Starting-pitcher adjustment (A_home, A_away).** Recommendation: **include it in v1.** Team-only Elo is expected to barely beat the home-rate baseline (§2), so without it the MLB model is not very informative.

The form is the FiveThirtyEight rolling game score, a fixed recipe and not a general player model:
- `game_score = 47.4 + 1.5·outs + K − 2·BB − 2·H − 3·R − 4·HR`, per start, from the boxscore.
- Each pitcher keeps an exponentially weighted rating `rGS_p` over his starts (decay α tuned).
- Each team has an analogous team rating `rGS_t` over all its starters' games.
- `A = c × (rGS_p − rGS_t)`, where c is tuned.
- A pitcher's first start uses `rGS_p = rGS_t`, i.e. A = 0.
- **Which pitcher.** From 2010 the announced *probable* pitcher is used (known before the game, no look-ahead). Before 2010 (warm-up only) the actual starter from the boxscore is used. That leaks late-scratch information into warm-up ratings only, never into validation or test predictions.
- **Openers:** a "starter" who records ≤ 3 outs in a planned opener role still gets a game score. No special opener logic exists in v1, and it is a limitation.

Cost: one boxscore request per game (~2,430 per season, ~62k in total), cached as compact parquets.

**[DECISION 4] K_playoff ≥ K_regular.** Recommendation: don't impose it (NHL, NBA and NFL all preferred the opposite).

**Grid:**

```
K_regular ∈ {2, 4, 6, 8}            (162 games: much smaller K than other sports)
K_playoff ∈ {2, 4, 6, 8}
carry     ∈ {0.50, 0.60, 0.70, 0.80}
H         ∈ {0, 15, 25, 35, 50}
mov       ∈ {off, on}
c         ∈ {0, 3, 4.7, 6}           (c = 0 → team-only Elo, reported for comparison)
α         ∈ {0.1, 0.2}               (pitcher rGS decay; unused when c = 0)
```

That is 4·4·4·5·2·4·2 = 5,120 cells; MLB backtests are larger, so expect tens of minutes.

---

## Section 6 — Evaluation

Primary **LL < 0.685**; **Brier 0.235–0.248**; **ECE < 0.03**; **beat the home-rate baseline**. Baselines: naive, home-rate, static rating, and **team-only Elo at the frozen K / carry / H with c = 0**, which shows what the pitcher term adds.

**One-pass breakdowns** (inherits NFL):
- per season;
- regular vs postseason;
- months (Apr–May / Jun–Aug / Sep–Oct);
- neutral site;
- probable-pitcher first start vs established;
- calibration buckets for each.

**[DECISION 5] Thresholds.** Recommendation as written.

## Sections 7–11

Inherit NFL §§7–11 with MLB test seasons substituted. §10 adds: no use of betting lines, MLB "win probability" fields, or any third-party projection systems (ZiPS, Steamer, etc.).

---

## Section 12 — MLB v1.1: live win probability

Interpretable logistic, three coefficients:

```
logit P = β0 + β1 · pre · (o / 54) + β2 · (d + s·RE(base, out)) / sqrt(o / 3 + 1)

pre = logit of the frozen pre-game P(home)
o   = outs remaining for both teams in regulation (54 at first pitch; extra innings use the current inning's)
d   = home − away runs
s   = +1 if home is batting, −1 if away
RE  = run expectancy for the current base-out state, a 24-cell table computed from the training seasons
```

- **Training:** 2010 → 2014 play-by-play from `feed/live`.
- **Evaluation:** once on 2022–2025.

**[DECISION 6] Live targets** (inherits NFL): beat the pre-game-held baseline in every third of the game; ECE < 0.03; first pitch within 0.02 of pre-game; monotone in d; leading by 5+ in the bottom of the 9th with 2 outs ≥ 0.97.

**Cost:** the live feed is ~1 request per game (~12k for training). Retrosheet event files are a fallback source if the volume is a problem; switching would be a version-tagged amendment.

---

## Section 13 — Known limitations (initial)

- **The pitcher adjustment is a fixed formula**, not a player model. No bullpen, lineup, platoon, park or weather modeling.
- **Openers and bullpen games** confuse the starter term.
- **Rule changes inside the window:** universal DH (2022), pitch clock / shift ban (2023), extra-inning runner (2020+).
- **The 2020 60-game season** is in validation, with no special handling.
- **Data terms:** MLB data is used under MLB Advanced Media's non-commercial terms; Tilt can't be commercialized on this data.
- **Ingest (N1, 2026-10-11):**
  - *Coverage:* every season 2000–2026 passes after the v1.1 validity rule; 35 scoreless "finals" were dropped in 2000.
  - *Starters:* starter lines come from ~62k boxscores.
  - *Probables:* both probable pitchers are present for 28,045 of 28,070 games in 2010–21; the actual starter is used for the other 25.
  - *Neutral sites (< 5 home games at that venue):* 0–12 per season, except **47 in 2020**. COVID make-ups often listed the "home" team batting last in the opponent's park, plus the Blue Jays' displaced games. Toronto's 26 games at Buffalo's Sahlen Field remain home games.
  - *Limitations:* the neutral rule cannot tell a true neutral site from a one-off relocated home game (e.g. hurricane moves). Both get no home bump.
- **Engine (N2):** on warm-up + validation the league mean stays at exactly 1500, ratings span 1398–1617, 1,854 pitchers are tracked, and team rGS spans 42–59. No new limitations beyond §5 / §13.
- **Frozen parameters (N3, 2026-10-11):** `K_regular 4, K_playoff 2, carry 0.60, H 25, mov on, c 3.0, α 0.1`, from the 5,120-cell grid on 2015–2021. Validation (n = 15,743): LL 0.67666, Brier 0.24188, ECE 0.00251. Baselines: naive 0.69315, home-rate 0.69049 (rate 53.65%), static 0.69984, **best team-only (c = 0) 0.67783**.
  - *H = 25 is inside the pre-registered 15–40.*
  - *The pitcher term helps modestly:* −0.0012 LL vs the best team-only cell.
  - ***Pre-registration miss:*** §2 expected team-only Elo to land within ~0.01 LL of the home-rate baseline. It beat it by 0.0127, so team strength alone carries more signal than predicted. The pitcher term widens that gap only slightly (to 0.0138), rather than "clearly".
  - *MOV helps marginally:* best MOV-off cell LL 0.67723.
  - *K_playoff = 2 is the grid floor and below K_regular,* the same direction as every other sport. The best cell honoring K_playoff ≥ K_regular is +0.00003 LL, i.e. noise.
  - *Home rate by validation season:* 54.1 / 53.0 / 54.3 / 52.8 / 53.0 / **55.8 (2020)** / 54.0%. No trend; §8 drift flag not fired.
- **Freeze run exited with code 134 (abort) after writing the artifact.** The 1.6 MB JSON is complete (all sections, 5,120 grid rows, winner = grid[0]), and recomputing the winner's validation metrics from scratch reproduced LL / Brier / ECE exactly. The abort hit during the final console summary; the cause was not diagnosed. Freezes are verified by recomputation, not by exit code.
- **No logos:** inherits NHL §13.I.

---

## Decisions (resolved 2026-10-11 — all as recommended)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Test window | 2022–2025 (~9,800 games) |
| 2 | Margin of victory | On/off in the grid |
| 3 | Starting-pitcher adjustment | **Include in v1** (FiveThirtyEight rolling game score; probable pitchers from 2010) |
| 4 | K_playoff ≥ K_regular | Do not impose |
| 5 | v1 thresholds | LL < 0.685, Brier 0.235–0.248, ECE < 0.03, beat home-rate baseline |
| 6 | v1.1 live targets | Pre-register as in §12 |

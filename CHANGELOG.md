# Changelog

All meaningful code and methodology changes are recorded here, per Section 11 of `METHODOLOGY.md`.

## 2026-10-11 — UI: per-sport "worlds" redesign

User request: the single dark theme was "very boring". Wanted more color and innovation, with sport colors (basketball orange, football green, hockey black, baseball red + blue).
- `styles.css` rewritten around per-sport tokens on `[data-sport]`: **NHL** black ice (frost cyan, rink lines), **NBA** hardwood (orange, court arcs), **NFL** turf (green, yard lines), **MLB** ballpark night (red + blue, stitches). Background glows and motif layers fade down the page.
- **Hero header:** italic gradient "TILT" wordmark + sport name, tagline, model-version chip. Fonts: Barlow Condensed / Inter / JetBrains Mono.
- **Sport switcher:** each pill always wears its own sport color, with a line-art glyph (puck + stick, basketball, football, baseball).
- **Tabs:** a segmented control. **Panels:** glass with an accent hairline. **Pass/fail list:** check/cross chips.
- **Game cards:** painted in the two teams' colors (corner glows, split top stripe, team-colored probability bars), tilted badges, a pulsing live dot. **Finished games now show the final score** (previously only live games showed a score).
- Phone layout: tabs scroll horizontally, ratings hidden on narrow cards.
- NFL pill status → "in development" with corrected copy (methodology approved).
- METHODOLOGY §13.I documents the theme change and team-color bar contrast. Correction: the NFL N1 entry below says 226 tests; the actual count is **227**.

## 2026-10-11 — NFL N1: ingest + lineage (methodology/NFL.md v1.0 approved)

Author approved `methodology/NFL.md` with all six decisions as recommended.
- `app/nfl/teams.py`: 32 franchises on current nflverse codes, era-code lineage (STL→LA, SD→LAC, OAK→LV), ESPN code mapping (LAR→LA, WSH→WAS), dark-theme display colors.
- `app/nfl/pipeline.py`: nflverse `games.csv` → `data_cache/nfl/games.parquet` keeping **only** the 11 §3-permitted columns, so betting lines never enter the repo. Loud failure on schema change. Per-season coverage in the manifest.
- Data: 1999 → 2026 schedule (92 KB). Every complete season passes coverage (2022: 271/272, the cancelled BUF–CIN game); 2026 in progress with 65 games played. Every historical code maps to a franchise.
- +10 tests (226). No rating code; no NFL metric computed.
- No new limitations beyond NFL §13; the column whitelist makes §10's "never read betting columns" structural rather than procedural.

## 2026-10-11 — NFL methodology v0.1-draft (pre-code)

New `methodology/NFL.md`, pending author approval.
- **Data:** nflverse `games.csv` (1999 → present; coverage counts match 248 / 256 / 272 schedules), nflverse play-by-play for v1.1, ESPN scoreboard for live. Betting columns and nflfastR/nflverse model outputs (`wp`, `vegas_wp`, `ep`, …) are explicitly never read.
- **Split:** warm-up 1999–2014, validation 2015–2021, test 2022–2025.
- **Model:** Elo with home bump (neutral-aware), FiveThirtyEight NFL MOV multiplier (ties use M = 1), 1,440-cell grid. QB adjustment deferred to v2 as the pre-registered largest error source.
- **v1.1:** five-term interpretable live logistic (pre-game edge, score, possession, field position).
- Six **[DECISION]** items, including pre-registered live-model targets (the NBA live model had none).
- Contamination disclosure: only column names, game counts, location split and team codes were seen.

## 2026-10-11 — NBA v1.1: live in-game win probability

Methodology v1.2 (pre-fit): minute-mark sampling, final-score validity rule, only ESPN `plays` read (never its win-probability / odds blocks), and an explicit note that §12 sets no pass/fail target.

- `app/nba/pbp.py`: ESPN summary → minute-mark states, clock parsing ("11:34" / "34.5"), validity check, per-season parquets at `data_cache/nba/pbp/` (1.2 MB). Training 2009-10 → 2017-18 (11,488 games kept, 90 final-score mismatches dropped); test 2024-25 + 2025-26 (2,627 kept).
- `app/nba/live_wp.py`: §12 features, pure-Python Newton logistic fit (no numpy), `predict`, §12 checks. `scripts/nba_live_wp_fit.py` → `artifacts/nba/live_wp_v1.json` (β0 +0.151, β1 +1.478, β2 +0.665). Refuses to refit without `--force`.
- `scripts/nba_live_wp_evaluate.py` (one-shot, `--confirm`, no overwrite): **live LL 0.464 vs 0.608 for the pre-game-held baseline; ECE 0.026**; beats the baseline every quarter. Q1 ECE 0.050 (worse than held, 0.025). §12 checks: monotone ✓, 20-point lead late ✓, **tip-off within 0.01 ✗ (gap 0.105)**.
- `/nba/games/today` now attaches `live_wp` to in-progress games (`api.live_block`); the frontend live bar renders it. NBA tag → v1.1.
- Render deploy verified: ESPN is reachable from the backend host.
- +9 tests (216).

## 2026-10-10 — NBA N5: API + dashboard (NBA goes live)

Backend:
- `app/nba/api.py` router under `/nba`: seasons, current ratings, per-season history (era codes like SEA/NJN/NOH, Finals champion), today's games (frozen-param pre-game probability, neutral-site aware, live score/clock from ESPN), calibration (locked results reshaped to the NHL contract plus home-rate baseline, flags, breakdowns), admin refresh. Lazy cache (~0.6 s build).
- `app/nba/teams.py`: dark-theme display colors and era-aware display codes. `espn.py` also captures live state + clock (not persisted).
- `/sports` reports NBA `live`. +6 API tests (207).

Frontend:
- Shared `src/types.ts` and `src/components/` (TrajectoryChart, TodaysGames, CalibrationPanel) parameterized by color lookup, league, period labels, footnote, params label. NHL dashboard rewired, with no behavior change except the corrected footnote ("frozen v1 model … deferred to v2" was stale).
- New `src/sports/nba/` dashboard: trajectories with Finals champion, today's games (Q1–Q4/OT labels), calibration with home-rate baseline row, pass list and a breakdown table with the §8 late-season flag. NBA pill is live with tag `v1`.
- Fixed a shared calibration-plot bug: a `Scatter` series without an x key drew each bucket's point a second time at the wrong x. Present on the NHL tab since v1; the metrics were never affected (NHL §13.K).
- Chart right margin widened so the 👑 champion label isn't clipped.

Docs: methodology/NBA.md §13 N5 limitations; NHL METHODOLOGY §13.K calibration-plot note; README NBA status, endpoints and frontend layout.

## 2026-10-10 — NBA N4: one-shot test evaluation (PASS ×4)

`scripts/nba_evaluate.py` (§10 #1 quarantined: `--confirm` required, refuses overwrite without `--force`, frozen artifact only, refuses if a test season fails coverage). Emits every §6 breakdown in the single pass: per season, regular vs postseason, early/mid/late segments (mean of both teams' game numbers, scaled boundaries), neutral site, calibration buckets for each, and §8 flags.

Ran once on 2024-25 + 2025-26 (n = 2,643): **LL 0.60744 PASS, Brier 0.20991 PASS, ECE 0.02590 PASS, beats home-rate baseline (0.68834) PASS.** Flags: postseason ECE 0.0549 (< 0.08, no flag); **late-segment ECE 2.85× mid (flag fired)**. The model is underconfident late, contradicting §2's predicted mechanism (rest) and consistent with tanking. 2025-26 alone ECE 0.0419. Written up in methodology/NBA.md §13 and the README. +10 guardrail/segment tests (201).

## 2026-10-10 — NBA N3: validation grid + freeze

- `app/nba/tuner.py`: §5 grid (5 × 5 × 4 × 6 × 2 = 1,200 cells), validation 2018-19 → 2023-24, selection by LL then ECE then Brier. Static-rating and home-rate baselines. Test seasons named but never loaded (`load_rows` asserts it).
- `scripts/nba_freeze.py`: runs the grid (~2 min), prints the §8 pre-freeze checks, writes `artifacts/nba/frozen_params.json` (winner + full grid + checks). Refuses to overwrite an existing freeze without `--force`.

**Frozen:** K_regular 15, K_playoff 10, carry 0.65, H 40, MOV on. Validation LL 0.63072 / Brier 0.22038 / ECE 0.01274 (n = 7,588) vs home-rate baseline LL 0.68573.

Pre-registration outcomes logged in methodology/NBA.md §13: H = 40 misses the 50–110 expectation but is not a bug (clean U-curve); K_playoff < K_regular again; MOV helps by 0.0028 LL; home rate swings 54.7–59.0% by season with no trend. +5 tests (191).

## 2026-10-10 — NBA N2: rating engine + walk-forward backtest

- `app/nba/ratings.py`: §5 rule. Elo via `core.elo.expected` with home bump (0 at neutral sites), binary W/L, fixed-constant MOV multiplier `(|MOV|+3)^0.8 / (7.5 + 0.006·D)` when `mov` is on, zero-sum update, regression to 1500.
- `app/nba/backtest.py`: predict-then-update replay from `first_model_season()`, once-per-boundary regression, 1500 expansion seed, predictions carrying the §6 breakdown fields (season type, neutral, team-game numbers, season length), optional per-season trajectories, `rows_by_season` reuse for the tuner.
- +11 tests (186): formula, zero-sum, MOV direction, 30 franchises from 2000-01, [1100, 1900] bounds and ±1 mean (MOV on and off), Bobcats seeded at 1500 in 2004-05, bubble pin (172 Lake Buena Vista games + 3 international = 175 neutral in 2019-20).

No validation or test metric computed yet.

## 2026-10-10 — NBA N1: ingest + lineage (methodology/NBA.md v1.1)

Author approved `methodology/NBA.md` with all seven decisions as recommended (v1.0).

New `backend/app/nba/` package:
- `espn.py`: per-day ESPN scoreboard client, strict parser (`SchemaError` on missing fields), retries, §3 neutral-site rule (ESPN flag or Lake Buena Vista for the bubble). Skips empty `{}` events.
- `teams.py`: 30 franchises keyed on ESPN team id (lineage = id), conventional abbreviations, ESPN-published colors.
- `pipeline.py`: one parquet per season at `data_cache/nba/raw/`, season window Sep 1 → Oct 31 filtered by ESPN season label, coverage check vs schedule (lockout/COVID overrides), `clean_rows()` validity rules, `first_model_season()` enforcing the no-bridging rule, CLI `ingest / status / recheck`.

Data: 34 seasons ingested (1993-94 → 2026-27 to date). Coverage PASS for every season except **1999-2000 (0.981, FAIL)**, so the warm-up starts in **2000-01**. Dropped on read: 85 phantom 0-0 finals, 6 same-day duplicates.

Methodology v1.1: validity rules, coverage outcome, §13 entries (phantom/duplicate rows, lost 1990s history, 2012-13 cancelled game). +13 tests (175 total). No rating code yet; no NBA metric computed.

## 2026-10-10 — NBA methodology v0.1-draft (pre-code)

New `methodology/NBA.md`, written before any NBA ingest or model code and pending author approval. Highlights: ESPN public API as the single source (official NBA endpoints blocked scripted access during the probe); coverage rule (season enters only if regular-season count is within 1% of schedule; verified 1993-94 onward on samples); split warm-up 1993-94 → 2017-18, validation 2018-19 → 2023-24, test 2024-25 + 2025-26; Elo with home-court bump and a FiveThirtyEight-style margin-of-victory multiplier (on/off in a 1,200-cell grid); neutral sites via ESPN `neutralSite` + Lake Buena Vista city rule for the 2020 bubble (ESPN doesn't flag it); lineage keyed on ESPN team ids (roster continuity); new home-rate baseline; every breakdown emitted in the single test pass; v1.1 live WP as a three-term logistic model. Seven **[DECISION]** items await the author. Includes a contamination disclosure of exactly what NBA data was seen before drafting.

Correction to the Phase 0 entry below: the suite is **162** tests (+4 API tests), not 167 / +5 as written there and in commit `2d3a1f2`.

## 2026-10-10 — Phase 0: multi-sport platform shell

First step of expanding Tilt from NHL-only to NHL / NBA / NFL / MLB, one sport at a time. **No NHL model change**: v2 validation metrics reproduce exactly after the refactor (n = 5,599, LL 0.66219, Brier 0.23495, ECE 0.01531), checked against the pre-refactor commit in a separate worktree.

Backend:
- `app/core/elo.py`: sport-agnostic `expected()` / `regress()`. NHL `ratings.win_probability` and `apply_decay` delegate to it.
- `main.py`: NHL endpoints moved onto an `APIRouter` mounted at the root (unchanged contract) and under `/nhl`. New `GET /sports` lists each sport's status.
- +5 API tests (sports listing; root vs `/nhl` parity on three routes). 167 tests pass.

Frontend:
- New shell `src/App.tsx`: header + sport switcher pills, path routing (`/nhl`, `/nba`, `/nfl`, `/mlb`; `/` → NHL), per-sport accent via `data-sport` (NBA blue). Non-live sports show a status panel.
- NHL dashboard + components + API module + team colors moved to `src/sports/nhl/`; shared `src/http.ts`. NHL calls stay on root paths so the frontend works against the older backend build still on Render.
- Header dot glow now follows the accent color.

Docs: README gains a sport-status table and the new layout; METHODOLOGY §13.K documents the duplicated routes, duplicated sport list, asymmetric NHL layout, and single-process/lazy-cache constraint. Corrected the README/§13.C v2 validation figures (n = 5,594 / ECE 0.01528 → n = 5,599 / ECE 0.01531, per the frozen artifact).

## 2026-10-10 — v2 test evaluation (FAIL ×3) + roll dashboard to 2026-27

**v2 test evaluation, run once per §10 #1.** Re-ingested 2025-26 in full first (the cached parquet stopped at 2026-05-18; the re-pull has 1,312 regular-season + 82 playoff games through the Cup Final on 2026-06-14). `scripts.evaluate --confirm` (no `--force`) on test season `[20252026]` with frozen v2 params (K_regular 10, K_playoff 10, decay_carry 0.85, home_bump 40):

| | LL | Brier | ECE |
|---|---:|---:|---:|
| v2 model | 0.69315 FAIL | 0.24982 FAIL | 0.05851 FAIL |
| naive 50% | 0.69315 | 0.25000 | 0.01937 |
| static rating | 0.70979 | 0.25747 | 0.08150 |

n = 1,394. Locked per §10 #2. v1 results snapshotted to `results/test_evaluation_v1.json` (byte-identical to the v1 file). Analysis in METHODOLOGY §13.C: home win rate fell from 56.3% (2024-25) to 52.2%, the model is overconfident above 0.6, and prior-season ratings were worse than a coin flip on this season.

**Evaluator guard fix (before the run).** `scripts/evaluate.py` refused on an existing results file *before* snapshotting v1, so the first v2 run would have needed `--force`. The snapshot now runs first, and only a v1 file with a byte-identical snapshot may be overwritten; v2+ files still require `--force`. `home_bump` is now recorded in the results file and banner. +2 guardrail tests.

**Backtest live-row fix.** `backtest._apply_one_game` now applies only `OFF`/`FINAL` rows. Previously LIVE rows (partial scores) would have been scored as final, and a tied LIVE row raised in `classify_outcome` and crashed the cache build — reproduced today with two tied in-progress 2026-27 games. All 70,328 historical completed rows are `OFF`, so no v1/v2 number changes. +1 test.

**Current season is derived, not hardcoded.** `main.py` drops `CURRENT_SEASON_ID = 20252026`; the Cup sim uses the latest ingested season. `/simulation/cup` returns `playoffs_started: false` with no teams before a bracket exists (+1 API test). `/healthz` now reports `home_bump`. Frontend: current season = newest row from `/seasons` (hero-chart refresh + Cup panel), Cup panel title derived from the season, a note replaces the panel pre-playoffs, header tag `v1` → `v2`.

**Data.** Ingested 2026-27 to date (81 completed regular-season games; first 84-game NHL season).

METHODOLOGY: status line + amendment-log "v2 evaluation record" entry; §13.C (v2 failure analysis, missing §8 playoff ECE breakdown), §13.D (live-row bug, 84-game schedule), §13.F (no Cup odds in regular season), §13.J (evaluator ordering bug, `home_bump` missing from v2 results file). README: v2 results table replaces "evaluation pending". 158 tests pass.

## 2026-05-19 — UI: NHL "broadcast graphics" dark theme

Theme refresh per user request after seeing the deployed dashboard looked flat. Adopts an NHL-branded dark aesthetic: charcoal background, silver-white text, NHL red (`#c8102e`) as the accent. Header gains a small red signal dot before the title, a 56px accent underline, and an uppercase wordmark feel. Tabs uppercase + spaced for a broadcast vibe; active tab gets red underline and a subtle background highlight. Probability bars get a slight inset shadow and bigger height for depth. Live games get a red glow + box-shadow ring. Team badges get a soft ring + drop shadow for premium feel.

Team color palette retuned for the dark theme (`frontend/src/teamColors.ts`):
- **BOS / PIT / LAK** flip back to their published gold/silver secondaries (their primary blacks vanish on dark).
- **COL / DAL / FLA / WPG / STL / TBL / TOR / VAN / MIN** get slightly lightened variants of their dark navy / green / burgundy primaries so the lines read against the dark bg.
- 23 other teams keep their original published primaries — they already read fine on dark.

METHODOLOGY.md §13.I: added a bullet documenting the theme + team-color coupling so a future contributor restoring the light theme also knows to restore the published primaries.

No methodology amendment. No backend code touched.

## 2026-05-19 — DEPLOY.md flipped to Render-first (free tier, no CC)

User constraint: no paid platforms for the backend. Render's free Web Service tier is still available and supports Dockerfile deploys directly, so it's now the primary walkthrough in `DEPLOY.md` (replacing Railway, which removed its free tier in 2023). Alternatives reordered:

- **Primary:** Render (free, no credit card, sleeps after 15 min idle with ~30-60 s cold start).
- **Alternative — always-on free:** Hugging Face Spaces with the Docker SDK. Free, no CC, code is public on the free tier.
- **Paid:** Fly.io (free monthly credit but requires CC) and Railway ($5/min) kept as honorable mentions.

No code changes. The `Dockerfile` was already host-agnostic (listens on `$PORT`), the CORS allow-list is already env-driven, and the parquet cache is already in the image. README's "Deploying" sentence updated to name Render as the recommended backend target.

No methodology amendment. §13.G "Deployment / operational limitations" already covers ephemeral container storage and idle-sleep cold start, which apply to Render the same way they applied to Railway.

## 2026-05-18 — Deploy-ready: Dockerfile + vercel.json + DEPLOY.md

The project now deploys cleanly to Vercel (frontend) + Railway/Render/Fly (backend) without per-deploy data ingest. The Parquet cache (~2 MB across 108 score seasons + 15 PBP seasons) is small enough to commit, so it's now tracked in git and ships in the container image. Backend cold start stays at ~1.5 s.

Backend:
  - `backend/Dockerfile`: python:3.12-slim, uv installed from the published image, layer-cached dep install before app code is copied. Listens on `$PORT` (Railway/Render/Fly inject it; defaults to 8000 locally).
  - `backend/.dockerignore`: excludes .venv, tests, scripts, caches.
  - `main.py`: CORS `allow_origins` is now read from the `CORS_ALLOWED_ORIGINS` env var (comma-separated), defaulting to the local-dev URLs. Existing tests still pass.

Frontend:
  - `frontend/vercel.json`: Vite preset, build/install commands, SPA rewrites.
  - No code changes; existing `VITE_API_BASE` handling already works against any backend URL.

Repo:
  - `.gitignore`: un-ignored `backend/data_cache/` with a note explaining why (deploy-ready snapshot).
  - All 123 parquet files now tracked (~2 MB total).

Docs:
  - `DEPLOY.md`: full walkthrough for Railway / Render / Fly + Vercel including env-var reference, post-deploy refresh procedure, free-tier ephemerality caveats, and a troubleshooting table.
  - `README.md`: added a "Deploying" section linking to DEPLOY.md.
  - `METHODOLOGY.md` §13: new subsection G "Deployment / operational limitations" documenting ephemeral container storage, idle-sleep cold start, and CORS-allowlist requirements. Subsequent subsections renumbered (G→H, H→I, I→J).

No methodology change; pure infra/operational addition. Tests: 154 still passing.

## 2026-05-18 — README refreshed for v2

Project README updated to reflect the v2 feature set. Added a Status block making the v1-locked / v2-evaluation-pending split unambiguous. v1 metrics table relabeled as the canonical v1 record per §10 #2; new v2 status block reports the validation numbers (LL 0.66219, Brier 0.23495, ECE 0.01528 across n=5,594) and explicitly notes that the v2 test evaluation is gated on the 2026 Stanley Cup Final.

Backend module table extended with `pbp_pipeline`, `standings`, `cup_simulator`, `live_wp`, `live_state`, marked by version of introduction. Scripts section lists `build_live_wp.py`. Endpoint table adds `/simulation/cup`, `/wp`, plus the new `cup_winner` fields on `/ratings/history`. Frontend section rewritten as a per-tab description with the new behaviors (cup-winner 👑 + crown, all-32 Cup odds bar chart on Trajectories; live WP overlay + period/clock on Today's games; team-colored badges for trademark-safe identity).

One-time-setup section now includes `pbp_pipeline ingest --all` (~15 min) and `build_live_wp` (~5 s) steps. Test count refreshed: 106 → 154. Disclaimer split into a v1 paragraph (numbers locked) and v2 paragraph (validation-only, test pending).

No methodology change; this is documentation refresh. No new §13 limitations introduced.

## 2026-05-18 — Cup probability panel below the trajectory chart

User-visible: when viewing the 2025-26 season on the Trajectories tab, a 32-team vertical bar chart now sits under the trajectory plot showing each team's Stanley Cup win probability from the v2.1 Monte Carlo sim. Bars sorted desc; teams not in the playoff field render at 0% with low opacity. Bars colored by each team's primary brand color (same palette as the trajectory lines and the Today's Games badges).

Backend (main.py):
  - `/simulation/cup` response extended to include all 32 active franchises rather than just the playoff field. Each row gets a `status` field with one of `alive`, `eliminated`, or `not_in_playoffs`. Teams not in the playoff field have `cup_probability: 0.0`. The change is additive; existing callers that read the `teams` array still work.

Frontend:
  - New `CupOdds` component (recharts BarChart, 260px tall, X-axis = team abbreviations rotated -45° for readability, Y-axis = Cup %).
  - `App.tsx` fetches `/simulation/cup` when entering the Trajectories tab and re-polls every 5 minutes (the sim is cheap but not free — 60s polling matches games/today's "I need to see this change fast" cadence, while Cup probabilities only move on completed games, so 5min is enough).
  - Panel hidden when viewing any season other than 2025-26 (no live Cup race for completed seasons; the 👑 marker on the trajectory chart is the historical analogue).
  - `api.ts`: new `CupTeam` + `CupResponse` types and `fetchCup()` helper.

No methodology change — the underlying Cup sim and rating model are unchanged. The panel is a new view on existing data, scoped to the in-progress season.

## 2026-05-18 — Cup winner 👑 marker on the trajectory chart

User-visible: when viewing a completed season's ratings trajectory, the Stanley Cup winner now gets a 👑 emoji at the end of their line, plus a thicker / higher-opacity line for visual prominence. In-progress seasons show no crown.

Backend:
  - `standings.cup_winner(season_id)`: returns the team-code champion for a season, derived from the SCF winner in the playoff bracket. Falls back to a hand-curated `CUP_WINNER_OVERRIDES` for the COVID-era bracket weirdness (2019-20, 2020-21 — both TBL, the published 8/4/2/1 chronological bucket can't disambiguate the non-standard formats).
  - `derive_playoff_state` rewritten from subset-membership (which mis-bucketed CF/SCF as R2 once all rounds completed — R1 winners are technically in every later round) to chronological bucketing (first 8 series = R1, next 4 = R2, etc.). All seasons since 2013 verified correct except the two COVID years handled via overrides.
  - `/ratings/history/{season}` adds `cup_winner` (team code) and `cup_winner_franchise` (stable franchise_id for chart join).

Frontend:
  - `TrajectoryChart`: when `cup_winner_franchise` matches a team, that line gets thicker (2.25 vs 1.5 stroke), full opacity, and a 👑 emoji rendered via `LabelList` at the line's last data point only.
  - `api.ts`: new `cup_winner` + `cup_winner_franchise` fields on `RatingsHistoryResponse`.

METHODOLOGY.md §13.D: added a bullet documenting the cup_winner derivation rule, the 8/4/2/1 bracket assumption, the COVID-era overrides, and the pre-1942 challenge-series caveat. Notes that the limitation affects only the dashboard's visual marker, not the rating model.

## 2026-05-18 — UI polish: center Today's Games card, colored team badges

Frontend tweaks to make the Today's Games tab feel less cramped and add team-color identity without trademark risk. Layout change: `.games-grid` switched from a 2-column grid to `flex-wrap: wrap` with `justify-content: center` so a single matchup centers cleanly and multiple matchups flow naturally as a row. Cards bumped to padding 22/28, max-width 640px, abbrev font 18px. New `TeamBadge` component renders a 44px circle filled with the team's primary color (already in `teamColors.ts`) with the three-letter abbreviation in white.

§13.H added documenting why we don't embed NHL team logos: registered trademarks, takedown risk on a student project. The colored-badge approach is the safe substitute. Previous §13.H "Methodology process limitations" renumbered to §13.I; content unchanged.

## 2026-05-18 — METHODOLOGY.md v2.3 + V2.D (live polling integration)

v2 continues. v2.3 wires the v2.2 stateless WP model into the dashboard's live flow. No new model logic; this is pure integration. New §16 documents the polling cadence (60 s, conditional on in-progress games), the live-state extraction rules, and the failure-containment story (a single bad PBP fetch never breaks `/games/today`). New §13.G consolidates the seven live-polling limitations (between-poll staleness, no SSE, per-request fan-out, intermission ambiguity, lazy re-engagement, no push notifications for state transitions, hero-chart depends on /admin/refresh).

Code:
  - `app/live_state.py`: NHL `/v1/gamecenter/{gid}/play-by-play` fetcher + parser, with score-max aggregation across goal events and time-remaining extraction from the latest play. Returns None on any failure so the caller can fall back.
  - `app/live_wp.py`: `get_model()` + `clear_cache()` for the runtime path.
  - `app/engine.py`: `todays_matchups` extended to fan out PBP fetches for LIVE/CRIT games and enrich each matchup with `live_state` and `live_wp` fields. Pre-game payload shape unchanged.
  - `frontend/src/api.ts`: new `LiveStateBlock` / `LiveWPBlock` types on Matchup.
  - `frontend/src/components/TodaysGames.tsx`: `GameCard` component now renders live period/clock, live score, and a second probability bar for the live WP when present. Pre-game bar dimmed; live bar full-opacity with a smoothing tag if the lookup hit a sparse bin.
  - `frontend/src/App.tsx`: 60 s polling for `/games/today` while any matchup is in progress; matching 60 s polling for `/ratings/history/20252026` while the Trajectories tab is viewing the current season.
  - 9 new tests in `test_live_state.py`.

Tests: 154 passing (was 145 at end of V2.C; 9 added).

## 2026-05-18 — METHODOLOGY.md v2.2 + V2.C (live in-game win probability)

v2 continues. v2.2 adds the third pre-registered v2 feature: live in-game win probability, implemented as **Interpretation B** — a separate empirical lookup model independent of the Elo rating engine. New §15 documents the bin structure (period × mins_remaining × clamped_score_diff), Bayesian smoothing for sparse bins (α=50, threshold=100), training window 2010-11 → 2024-25, and the relationship to §10 #1 (2025-26 is held out from the WP training corpus).

Code:
  - `app/pbp_pipeline.py`: async goal-event ingest from `/v1/gamecenter/{gameId}/play-by-play` per training-window game. Per-season parquet at `data_cache/pbp_goals/{season}.parquet` + manifest. CLI: `python -m app.pbp_pipeline ingest --all|--season|--since|--force`, `status`.
  - `app/live_wp.py`: minute-by-minute sample expansion, smoothed bin lookup, artifact roundtrip JSON.
  - `scripts/build_live_wp.py`: one-shot script that walks every PBP parquet, builds the model, writes `artifacts/live_wp_v2.json`, and prints spot-check WP at canonical states (game start, P3 with 1-goal lead, OT tied, etc.).
  - `app/main.py`: new endpoint `GET /wp?period=&time_remaining_s=&score_diff=` — stateless lookup returning home win probability + sample count + smoothing flag.
  - 11 new tests in `test_live_wp.py` covering clamp/bucket helpers, smoothing math, sample expansion for zero-goal and one-goal games, artifact roundtrip, integration sanity (home-win baseline, monotonicity in well-sampled bins).

V2.C results (15 training seasons, 19,092 games, 1.17M samples, 631 bins):
  - Game start (P1, 19:30 left, 0-0): WP=0.542 (matches empirical home win rate over 2010-2025)
  - P3 start with 1-goal lead: WP=0.772 (in §15 pre-registered [0.75, 0.85] band)
  - P3 1 min remaining, up 1: WP=0.933
  - P3 1 min remaining, up 5 (clamped): WP=1.000
  - All well-sampled bins monotone in score_diff at fixed (period, mins_remaining).

Live polling of in-progress games is deferred to v2.3 — V2.C exposes the stateless model only.

## 2026-05-18 — METHODOLOGY.md §13.F (Cup-sim approximations documented)

New subsection F under §13 (Known limitations) lists the five approximations the Cup simulator makes: rating-independent outcome-type sampling, hardcoded conference membership, regular-season-points-only higher-seed inference for not-yet-started series, single-season outcome distribution baseline, no special goalie/fatigue handling in playoff series. The original "F. Methodology process limitations" is renamed to G to preserve its content while making room.

## 2026-05-18 — METHODOLOGY.md v2.1 + V2.B (Monte Carlo Cup probabilities)

v2 continues. v2.1 adds the second pre-registered v2 feature: Monte Carlo Cup probabilities. New §14 documents the simulation algorithm (per-game rating updates within a single sim run, 10,000 sims per call, in-progress series resumed from current state), the §10 #1 quarantine reasoning (forward projection ≠ test evaluation), and pre-registered expectations (probabilities sum to 1.0, ±1% CI at N=10k). No change to the rating model itself — the frozen v2.0 artifact drives the sim.

## 2026-05-18 — METHODOLOGY.md §13 (known limitations consolidated)

New Section 13 collects every limitation surfaced during v1 development and v2.0 work into a single auditable page: scope-deferred features, design choices that bound expressivity, empirical tensions between methodology and data (notably the §5 K_playoff≥K_regular constraint cost), data-quality limitations including pre-1967 sparseness and isolated NHL API 5xx errors, franchise-lineage judgment calls (Hamilton→NY Americans, OAK/CGS/CLE merger, etc.), and methodology-process limitations (shrinking test sets, no cross-validation safety net, no external comparison anchor). Material is cross-referenced rather than duplicated; nothing already in §2/§4/§5/§8/§10/§12 was rewritten.

## 2026-05-18 — METHODOLOGY.md v2.0 + V2.A (home-ice advantage)

v2 begins. The v1 model is locked at commit `f7548f6`; v1 artifacts (`frozen_params_v1.json`, `test_evaluation_v1.json`) are preserved alongside the new v2 artifacts.

Methodology: new §12 introduces `HOME_BUMP` as a tunable rating-point bias applied to the home team in `win_probability`. The v1 calibration result (every bucket under-predicted home wins by 3-8 points) is the direct motivation — §5 explicitly predicted this would happen when omitting home ice. v2 train/val/test split: 1967-2020 train, 2021-22 → 2024-25 validation (former v1 test seasons folded in), **2025-26 as the new held-out test** (touched exactly once at v2 final evaluation after the 2026 Cup Final).

Code: `ratings.win_probability` accepts an optional `home_bump`. `backtest.BacktestParams` gains the field; `_apply_one_game` passes it through. `metrics.static_rating_probs` accepts it. `tuner.GridPoint` expands to four dimensions; `DEFAULT_GRID` grows from 100 cells to 600. `freeze_params.py` writes both `frozen_params.json` (latest) and `frozen_params_v2.json` (versioned snapshot) and preserves the v1 artifact untouched. `historical.FrozenParams` is backwards-compatible (defaults `home_bump` to 0 when missing).

V2.A pre-registered expectations (in §12): optimal HOME_BUMP ∈ [30, 70] Elo points; validation log-loss improves by ≥ 0.005 vs v1 on the same window; validation ECE drops below 0.04. v2 test-set evaluation is deferred until 2025-26 is complete.

## 2026-05-18 — v1 ready for `v1 complete` commit

All §9 stopping criteria met except #10 (operator-action commit). The frozen v1 model passes log-loss and Brier targets on the held-out test set, misses ECE by 0.012 (driven by 2024-25 alone; 2023-24 meets the target). Documented systematic under-prediction of home wins across all buckets — anticipated v2 fix is home-ice modeling. See [`docs/STOPPING_CRITERIA.md`](./docs/STOPPING_CRITERIA.md) for the per-criterion walkthrough.

Final test-set numbers (n=2,798): model LL=0.67102, Brier=0.23921, ECE=0.05164. Beats both baselines on LL and Brier.

## 2026-05-18 — Phase E (release prep)

- README assembled per §9 #9: methodology summary, §6 metrics table, calibration buckets (n ≥ 30), methodology link, student disclaimer.
- `docs/STOPPING_CRITERIA.md` walkthrough mapping each §9 criterion to its evidence.
- This changelog entry covering Phases A–D below.

## 2026-05-18 — Phase D (frontend + API wired to frozen model)

- New `backend/app/historical.py` loads `artifacts/frozen_params.json`, replays every ingested season with the v1.2 engine, caches per-season per-franchise trajectories at startup (~1.5 s).
- Rewrote `backend/app/engine.py` to delegate ratings to `historical` and own only the live `/games/today` NHL schedule lookup + on-demand refresh.
- New endpoints: `/seasons` (108 rows with `pre_1967` flag), `/calibration/current` (reads `test_evaluation.json`). `/games/today` flips `frozen_params: true`. `/ratings/history/{season}` extended to any season with defunct-franchise tagging.
- Frontend gained a third tab "Calibration" with the §6 metrics table + bucket plot. Season selector populates all 108 seasons; pre-1967 selection shows the §2/§3 disclaimer banner. Trajectory chart's y-axis now auto-scales.
- 7 new FastAPI TestClient tests in `tests/test_api.py`. 106 backend tests total.

## 2026-05-18 — Phase C (validation freeze + test-set evaluation)

- New `backend/app/metrics.py`: Brier, log-loss (with eps clipping), ECE, calibration buckets, naive and static-rating baselines per §6.
- New `backend/app/tuner.py`: grid search over (K_regular, K_playoff, decay_carry); selection by lowest log-loss with deterministic tiebreaks (ECE then Brier).
- New `backend/scripts/freeze_params.py`: runs the grid, applies the §5 K_playoff ≥ K_regular constraint, writes `artifacts/frozen_params.json`. Frozen winner: **K_regular=10.0, K_playoff=10.0, decay_carry=0.85**. The unconstrained winner (K=12/6/c=0.85) is preserved in the artifact for transparency.
- New `backend/scripts/evaluate.py`: §10 #1 quarantined test-set evaluator. Refuses to run without `--confirm`; refuses to overwrite existing results without `--force`. Run exactly once on 2026-05-18 03:48 UTC.
- Tests: 16 metrics tests + 4 tuner tests + 2 evaluate-guardrail tests.

## 2026-05-18 — Phase B (full rating engine: lineage, decay, ties, mergers)

- New `backend/app/franchises.py`: hand-curated lineage table covering 8 modern relocations, 2 multi-rebrand franchises (TOR/DET), 6 pre-1967 defunct franchises, and the OAK/CGS/CLE → MNS merger per §4 v1.2.
- New `backend/app/backtest.py`: walk-forward replay engine. Loads Parquet seasons in order, applies cross-season decay, joins to franchise lineage, seeds expansion teams at 1500 on first appearance, applies the 1978 merger (simple-average rule).
- Extended `backend/app/ratings.py`: `apply_decay()` per §4; `classify_outcome()` with era-gated TIE detection that raises `ValueError` on impossible post-2005-06 equal-score regulation games.
- Tests: 15 lineage transition tests + 17 ratings_v2 tests + 10 backtest integration tests. Full smoke replay 1967-68 → 2021-22 ran in ~1 s with 55,305 games processed and league mean exactly 1500.

## 2026-05-18 — Phase A (idempotent NHL API ingest)

- New `backend/app/pipeline.py`: pulls every game from `/v1/score/{date}` across each season's window and writes one Parquet per season to `backend/data_cache/raw/`. Atomic writes via tmp+rename. Manifest at `data_cache/manifest.json`.
- New `backend/app/seasons.py`: season-id parsing, date range, pre-1967 flag.
- CLI: `python -m app.pipeline ingest --season|--all|--since`, `list`, `status`.
- Tolerant of persistent 5xx errors (treats as empty day) so the NHL API serving 500 for some preseason dates doesn't kill a multi-season run.
- Ingested all **108 seasons** (1917-18 → 2025-26), ~72,698 total game rows on disk.

## 2026-05-17 — METHODOLOGY.md v1.2
Resolves a single ambiguity introduced in v1.1 §4: how the OAK / CGS / CLE → MNS merger of 1978 should affect the surviving franchise's rating. v1.2 specifies the **simple average** rule — at the start of 1978-79, the Dallas Stars lineage (then MNS) begins the season at the arithmetic mean of MNS's and the absorbed chain's final 1977-78 ratings, after which the standard between-season decay applies. Resolved before any backtest evaluation or parameter tuning; the held-out test set has not been touched. The same rule applies by default to any future merger.

## 2026-05-17 — METHODOLOGY.md v1.1
Folded six pre-code clarifications into the methodology document before any implementation work. No model behavior was introduced that was not implied by v1.0; all changes resolve ambiguities flagged during a methodology review:

1. Section 4 — Expansion teams start at exactly 1500 in their debut season with no decay step applied; the decay rule applies normally from season 2 onward. Applies uniformly to the 1967-68 expansion six, Vegas 2017-18, Seattle 2021-22, etc.
2. Section 4 — Franchise rating persists across relocations. The new-city team inherits the prior-city team's most recent rating with no reset. Documented examples cover Atlanta→Calgary, Colorado Rockies→New Jersey, Minnesota North Stars→Dallas, Quebec→Colorado, Hartford→Carolina, Atlanta Thrashers→Winnipeg, and the California/Cleveland→Minnesota merger.
3. Section 5 — Tie outcome weight is 0.50 for both teams (pre-2005-06 seasons only). Added as a row to the outcome weights table; fixed, not tunable.
4. Section 5 — Playoff K=10 is uniform across all playoff games regardless of round or series state. Series-context adjustment remains deferred to V3.
5. Section 5 — `/games/today` must compute live probabilities using the parameter set frozen at the end of validation. Rating state updates as new results land; parameters do not. Stated as a code-level invariant.
6. Sections 2 and 6 — Brier score upper bound tightened from 0.250 to 0.245, bringing Brier target stringency roughly in line with the log-loss target (<0.685).

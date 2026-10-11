import { SportDashboard, type SportConfig } from "../../components/SportDashboard";
import { getJson } from "../../http";
import type { RatingsHistoryResponse, SeasonsResponse, TodayResponse } from "../../types";
import type { SportCalibration } from "../../components/SportDashboard";

const cfg: SportConfig = {
  league: "MLB",
  subhead:
    "Elo ratings with home field, margin of victory, and a starting-pitcher adjustment (rolling game score), frozen on 2015–2021 and evaluated once on 2022–2025. Data: MLB Advanced Media (non-commercial use). See methodology/MLB.md.",
  todayLabel: "Today's games",
  periodLabel: (p) => `Inn ${p}`,
  emptyNote: "Spring training and exhibitions aren't modeled.",
  footnote:
    "Pre-game probabilities from the frozen MLB v1 model (incl. probable starters); live probabilities from the v1.1 base-out model (score, inning, outs, runners), refreshed every 60 s. Pre-game postseason calibration was poor in testing, so read October pre-game numbers with caution.",
  championLabel: (team, season) => `${team} won the ${season} World Series`,
  breakdownRows: [
    ["2022", (b) => b.per_season["2022"]],
    ["2023", (b) => b.per_season["2023"]],
    ["2024", (b) => b.per_season["2024"]],
    ["2025", (b) => b.per_season["2025"]],
    ["Regular season", (b) => b.regular_season],
    ["Postseason", (b) => b.postseason],
    ["Apr–May", (b) => b.segments.early],
    ["Jun–Aug", (b) => b.segments.mid],
    ["Sep–Oct", (b) => b.segments.late],
    ["Starter's first start", (b) => b.pitcher_first_start],
    ["Established starters", (b) => b.pitchers_established],
    ["Neutral site", (b) => b.neutral_site],
  ],
  flagNotes: (cal) =>
    cal.flags.postseason_ece_above_0_08
      ? ["§8 flag: postseason ECE exceeds 0.08, and postseason log-loss is worse than a coin flip (171 games). The regular-season model doesn't transfer to October."]
      : [],
  api: {
    seasons: () => getJson<SeasonsResponse>("/mlb/seasons"),
    history: (s: number) => getJson<RatingsHistoryResponse>(`/mlb/ratings/history/${s}`),
    today: () => getJson<TodayResponse>("/mlb/games/today"),
    calibration: () => getJson<SportCalibration>("/mlb/calibration/current"),
  },
};

export function MlbDashboard() {
  return <SportDashboard cfg={cfg} />;
}

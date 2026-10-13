import { SportDashboard, type SportConfig, type SportCalibration } from "../../components/SportDashboard";
import { getJson } from "../../http";
import type { RatingsHistoryResponse, SeasonsResponse, TodayResponse } from "../../types";

const cfg: SportConfig = {
  league: "FBS",
  sport: "cfb",
  oddsLabel: "Projected records",
  subhead:
    "Elo ratings for FBS teams with home field and margin of victory; FCS opponents share one pooled rating. Frozen on 2014–2021 and evaluated once on 2022–2025 (FBS-vs-FBS games). The trajectory chart shows each season's top 25 plus the champion. See methodology/CFB.md.",
  todayLabel: "This week",
  periodLabel: (p) => (p <= 4 ? `Q${p}` : "OT"),
  emptyNote: "No FBS games this week.",
  footnote:
    "Pre-game probabilities from the frozen CFB v1 model; live probabilities from the v1.1 in-game model (score, time, possession, field position). FCS opponents use the pooled FCS rating. Bowl/playoff pre-game calibration and overtime live probabilities were weak in testing.",
  championLabel: (team, season) => `${team} won the ${season} national championship`,
  breakdownRows: [
    ["2022", (b) => b.per_season["2022"]],
    ["2023", (b) => b.per_season["2023"]],
    ["2024", (b) => b.per_season["2024"]],
    ["2025", (b) => b.per_season["2025"]],
    ["Regular season", (b) => b.regular_season],
    ["Bowls + playoff", (b) => b.postseason],
    ["Weeks 1–4", (b) => b.segments.early],
    ["Weeks 5–10", (b) => b.segments.mid],
    ["Weeks 11+", (b) => b.segments.late],
    ["Conference games", (b) => b.conference],
    ["Non-conference", (b) => b.non_conference],
    ["Neutral site", (b) => b.neutral_site],
  ],
  flagNotes: (cal) =>
    cal.flags.postseason_ece_above_0_08
      ? ["§8 flag: bowl and playoff ECE exceeds 0.08 (176 games), with log-loss barely below a coin flip — opt-outs, interim coaches and layoffs aren't modeled."]
      : [],
  api: {
    seasons: () => getJson<SeasonsResponse>("/cfb/seasons"),
    history: (s: number) => getJson<RatingsHistoryResponse>(`/cfb/ratings/history/${s}`),
    today: () => getJson<TodayResponse>("/cfb/games/today"),
    calibration: () => getJson<SportCalibration>("/cfb/calibration/current"),
  },
};

export function CfbDashboard() {
  return <SportDashboard cfg={cfg} />;
}

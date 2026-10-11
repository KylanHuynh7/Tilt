import { SportDashboard, type SportConfig } from "../../components/SportDashboard";
import { nbaApi } from "./api";

const cfg: SportConfig = {
  league: "NBA",
  subhead:
    "Elo ratings with home-court and margin-of-victory adjustments, frozen on 2018-19 → 2023-24 and evaluated once on 2024-25 + 2025-26. See methodology/NBA.md.",
  todayLabel: "Today's games",
  // ESPN periods: 1-4 quarters, 5 = OT, 6 = 2OT, …
  periodLabel: (p) => (p <= 4 ? `Q${p}` : p === 5 ? "OT" : `${p - 4}OT`),
  emptyNote: "Preseason and exhibition games aren't modeled.",
  footnote:
    "Pre-game probabilities from the frozen NBA v1 model; live probabilities from the v1.1 in-game model (score margin, time left, and pre-game edge), refreshed every 60 s.",
  championLabel: (team, season) => `${team} won the ${season} NBA Finals`,
  breakdownRows: [
    ["2024-25", (b) => b.per_season["20242025"]],
    ["2025-26", (b) => b.per_season["20252026"]],
    ["Regular season", (b) => b.regular_season],
    ["Play-in + playoffs", (b) => b.postseason_play_in_and_playoffs],
    ["Early season", (b) => b.segments.early],
    ["Mid season", (b) => b.segments.mid],
    ["Late season", (b) => b.segments.late],
    ["Neutral site", (b) => b.neutral_site],
  ],
  flagNotes: (cal) =>
    cal.flags.late_segment_ece_over_2x_mid
      ? [
          `§8 flag: late-season ECE is ${Number(cal.flags.late_over_mid_ece_ratio).toFixed(2)}× mid-season. The model is underconfident late (favorites win more often than predicted), the opposite of the pre-registered rest effect and consistent with tanking. Neutral-site figures rest on very few games.`,
        ]
      : [],
  api: nbaApi,
};

export function NbaDashboard() {
  return <SportDashboard cfg={cfg} />;
}

import { SportDashboard, type SportConfig } from "../../components/SportDashboard";
import { nflApi } from "./api";

const cfg: SportConfig = {
  league: "NFL",
  subhead:
    "Elo ratings with home-field and margin-of-victory adjustments, frozen on 2015–2021 and evaluated once on 2022–2025. No quarterback model yet — see methodology/NFL.md.",
  todayLabel: "This week",
  periodLabel: (p) => (p <= 4 ? `Q${p}` : "OT"),
  emptyNote: "No regular-season or playoff games this week.",
  footnote:
    "Pre-game probabilities from the frozen NFL v1 model. Starting-QB changes aren't modeled. Live score and clock refresh every 60 s; a live win probability arrives in NFL v1.1.",
  championLabel: (team, season) => `${team} won the ${season} season's Super Bowl`,
  breakdownRows: [
    ["2022", (b) => b.per_season["2022"]],
    ["2023", (b) => b.per_season["2023"]],
    ["2024", (b) => b.per_season["2024"]],
    ["2025", (b) => b.per_season["2025"]],
    ["Regular season", (b) => b.regular_season],
    ["Playoffs", (b) => b.playoffs],
    ["Weeks 1–4", (b) => b.segments.early],
    ["Mid season", (b) => b.segments.mid],
    ["Final 2 weeks", (b) => b.segments.late],
    ["Neutral site", (b) => b.neutral_site],
  ],
  flagNotes: (cal) =>
    cal.flags.playoff_ece_above_0_08
      ? [
          "§8 flag: playoff ECE exceeds 0.08. It rests on only 52 playoff games across ten buckets, so much of it is noise, but the pre-registered rule says to report it here, not bury it.",
        ]
      : [],
  api: nflApi,
};

export function NflDashboard() {
  return <SportDashboard cfg={cfg} />;
}

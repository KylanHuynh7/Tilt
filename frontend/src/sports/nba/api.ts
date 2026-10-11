import { getJson } from "../../http";
import type {
  CalibrationResponse,
  MetricBlock,
  RatingsHistoryResponse,
  SeasonsResponse,
  TodayResponse,
} from "../../types";

// NBA extras on top of the shared calibration contract (methodology/NBA.md §6).
type Breakdown = { n: number; model?: MetricBlock };
export type NbaCalibrationResponse = CalibrationResponse & {
  verdict: Record<string, "PASS" | "FAIL">;
  flags: {
    postseason_ece_above_0_08: boolean;
    late_segment_ece_over_2x_mid: boolean;
    late_over_mid_ece_ratio: number | null;
  };
  breakdowns: {
    per_season: Record<string, Breakdown>;
    regular_season: Breakdown;
    postseason_play_in_and_playoffs: Breakdown;
    segments: Record<"early" | "mid" | "late", Breakdown>;
    neutral_site: Breakdown;
  };
};

export const fetchNbaSeasons = () => getJson<SeasonsResponse>("/nba/seasons");
export const fetchNbaHistory = (season: number) =>
  getJson<RatingsHistoryResponse>(`/nba/ratings/history/${season}`);
export const fetchNbaToday = () => getJson<TodayResponse>("/nba/games/today");
export const fetchNbaCalibration = () => getJson<NbaCalibrationResponse>("/nba/calibration/current");

import { getJson } from "../../http";

export type {
  SeasonRow,
  SeasonsResponse,
  HistoryPoint,
  TeamHistory,
  RatingsHistoryResponse,
  LiveStateBlock,
  LiveWPBlock,
  Matchup,
  TodayResponse,
  CalibrationBucket,
  MetricBlock,
  CalibrationResponse,
} from "../../types";
import type { CalibrationResponse, RatingsHistoryResponse, ScorerRow, SeasonsResponse, TodayResponse } from "../../types";

export type CupTeam = {
  team: string;
  name: string;
  rating: number;
  cup_probability: number;
  alive: boolean;
  status: "alive" | "eliminated" | "not_in_playoffs";
};
export type CupResponse = {
  season: number;
  playoffs_started: boolean;   // false → no bracket yet; teams is empty
  simulated_at: string;
  n_simulations: number;
  wall_seconds: number;
  current_round: number;
  in_progress_series: string[];
  teams: CupTeam[];
  frozen_params: { k_playoff: number; home_bump: number; methodology_version: string };
};

export const fetchSeasons = () => getJson<SeasonsResponse>("/seasons");
export const fetchHistory = (season: number) =>
  getJson<RatingsHistoryResponse>(`/ratings/history/${season}`);
export const fetchToday = () => getJson<TodayResponse>("/games/today");
export const fetchCalibration = () => getJson<CalibrationResponse>("/calibration/current");
export const fetchCup = () => getJson<CupResponse>("/simulation/cup");
export type ScorersResponse = { available: boolean; ready: boolean; date?: string; players: ScorerRow[]; note?: string };
export const fetchScorers = () => getJson<ScorersResponse>("/projections/today");

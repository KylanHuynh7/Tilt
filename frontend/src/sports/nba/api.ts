import { getJson } from "../../http";
import type { RatingsHistoryResponse, SeasonsResponse, TodayResponse } from "../../types";
import type { SportCalibration } from "../../components/SportDashboard";

export const nbaApi = {
  seasons: () => getJson<SeasonsResponse>("/nba/seasons"),
  history: (season: number) => getJson<RatingsHistoryResponse>(`/nba/ratings/history/${season}`),
  today: () => getJson<TodayResponse>("/nba/games/today"),
  calibration: () => getJson<SportCalibration>("/nba/calibration/current"),
};

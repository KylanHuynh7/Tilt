import { getJson } from "../../http";
import type { RatingsHistoryResponse, SeasonsResponse, TodayResponse } from "../../types";
import type { SportCalibration } from "../../components/SportDashboard";

export const nflApi = {
  seasons: () => getJson<SeasonsResponse>("/nfl/seasons"),
  history: (season: number) => getJson<RatingsHistoryResponse>(`/nfl/ratings/history/${season}`),
  today: () => getJson<TodayResponse>("/nfl/games/today"),
  calibration: () => getJson<SportCalibration>("/nfl/calibration/current"),
};

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export type SeasonRow = { season_id: number; label: string; pre_1967: boolean };
export type SeasonsResponse = { count: number; seasons: SeasonRow[] };

export type HistoryPoint = { game_id: number | null; date: string; rating: number };
export type TeamHistory = {
  franchise_id: string;
  team: string | null;
  name: string;
  is_defunct: boolean;
  points: HistoryPoint[];
};
export type RatingsHistoryResponse = {
  season: number;
  label: string;
  pre_1967: boolean;
  n_franchises: number;
  teams: TeamHistory[];
};

export type Matchup = {
  game_id: number;
  game_date: string;
  state: string;
  home: string;
  away: string;
  home_rating: number;
  away_rating: number;
  home_win_prob: number;
  away_win_prob: number;
  home_score: number | null;
  away_score: number | null;
};
export type TodayResponse = {
  date: string;
  frozen_params: boolean;
  matchups: Matchup[];
};

export type CalibrationBucket = {
  lo: number;
  hi: number;
  n: number;
  mean_predicted: number;
  mean_actual: number;
};
export type MetricBlock = { n: number; brier: number; log_loss: number; ece: number };
export type CalibrationResponse = {
  evaluated_at: string;
  methodology_version: string;
  frozen_at: string;
  frozen_params: { k_regular: number; k_playoff: number; decay_carry: number };
  warmup_seasons: number[];
  test_seasons: number[];
  n_test_predictions: number;
  metrics: {
    model: MetricBlock;
    naive_baseline: MetricBlock;
    static_rating_baseline: MetricBlock;
  };
  per_season: Record<string, {
    model: MetricBlock;
    naive_baseline: MetricBlock;
    static_rating_baseline: MetricBlock;
  }>;
  calibration_buckets: CalibrationBucket[];
  section_6_targets: { log_loss_max: number; brier_band: [number, number]; ece_max: number };
};

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${path}`);
  return (await res.json()) as T;
}

export const fetchSeasons = () => getJson<SeasonsResponse>("/seasons");
export const fetchHistory = (season: number) =>
  getJson<RatingsHistoryResponse>(`/ratings/history/${season}`);
export const fetchToday = () => getJson<TodayResponse>("/games/today");
export const fetchCalibration = () => getJson<CalibrationResponse>("/calibration/current");

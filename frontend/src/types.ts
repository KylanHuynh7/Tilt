// Response shapes shared by every sport whose API follows the NHL contract.

export type SeasonRow = { season_id: number; label: string; pre_1967: boolean };
export type SeasonsResponse = { count: number; seasons: SeasonRow[] };

export type HistoryPoint = { game_id: number | null; date: string; rating: number };
export type TeamHistory = {
  franchise_id: string;
  team: string | null;
  name: string;
  is_defunct: boolean;
  color?: string;          // sports that ship display colors in the payload (NBA)
  points: HistoryPoint[];
};
export type RatingsHistoryResponse = {
  season: number;
  label: string;
  pre_1967: boolean;
  n_franchises: number;
  cup_winner: string | null;             // 3-letter team code, or null
  cup_winner_franchise: string | null;   // stable franchise_id, or null
  teams: TeamHistory[];
};

export type LiveStateBlock = {
  label?: string;          // sports without a clock (MLB: "Top 7 · 2 out")
  game_state: string;
  period: number;
  time_remaining_s: number;
  home_score: number;
  away_score: number;
};
export type LiveWPBlock = {
  home_win_prob: number;
  n_samples: number;
  smoothed: boolean;
};
export type Matchup = {
  postseason_lambda?: number | null;   // methodology/POSTSEASON.md: shrink applied to the published p
  raw_home_win_prob?: number;
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
  home_color?: string;     // NBA ships badge colors in the payload
  away_color?: string;
  neutral?: boolean;
  series?: string | null;  // MLB postseason series name
  pitching?: { home: PitcherSide; away: PitcherSide };
  // v2.3 §16 — present when the game is LIVE/CRIT and the PBP fetch succeeded.
  live_state?: LiveStateBlock;
  live_wp?: LiveWPBlock;
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
  frozen_params: { k_regular: number; k_playoff: number; decay_carry: number; [k: string]: number | boolean };
  warmup_seasons: number[];
  test_seasons: number[];
  n_test_predictions: number;
  metrics: {
    model: MetricBlock;
    naive_baseline: MetricBlock;
    static_rating_baseline: MetricBlock;
    home_rate_baseline?: MetricBlock;  // NBA §6
  };
  per_season: Record<string, {
    model: MetricBlock;
    naive_baseline: MetricBlock;
    static_rating_baseline: MetricBlock;
  }>;
  calibration_buckets: CalibrationBucket[];
  section_6_targets: { log_loss_max: number; brier_band: [number, number]; ece_max: number };
};

export type PitcherSide = {
  id: number | null; name: string | null; rolling_game_score: number | null;
  team_rolling_game_score: number | null; adjustment_elo: number; first_start: boolean; headshot: string | null;
};

// ---- Game detail (shared by NHL / NBA / NFL / MLB) ---------------------------

export type FormGame = {
  date: string; season: string | null; opponent: string; at_home: boolean;
  for: number; against: number; result: "W" | "L" | "T";
};
export type RosterPlayer = {
  id: string | null; name: string; position: string | null; jersey: string | null;
  headshot: string | null; status: string | null;
};
export type PlayerStatsCategory = {
  name: string; display_name: string; labels: string[]; descriptions: string[];
  seasons: { season: string | null; year: number | null; team: string | null; stats: string[] }[];
  career: string[];
};
export type PlayerStatsResponse = { sport: string; athlete_id: string; categories: PlayerStatsCategory[]; source: string };
export type Roster = {
  loaded: boolean;
  available: { group: string; players: RosterPlayer[] }[];     // healthy + game-time decisions
  ruled_out: (RosterPlayer & { reason: string })[];           // out, IR, suspended
  source: string;
  lineup?: Lineup | null;     // depth chart / batting order when published
  lineup_note?: string | null;
};
export type LineupSlot = { slot: string; label: string | null; starters: RosterPlayer[]; depth: RosterPlayer[] };
export type Lineup = {
  source: string;
  units: { unit: string; formation: string; slots: LineupSlot[] }[];
  others: RosterPlayer[];
};
export type DetailSide = {
  code: string; name: string; color: string | null;
  form: FormGame[]; roster: Roster;
  trend: { season: string | null; points: { date: string; rating: number }[] };
};
export type GameDetailResponse = {
  sport: string;
  game: Matchup;
  probability: {
    home_win_prob: number; rating_gap: number; p_home_without_home_edge: number;
    home_edge_elo: number; home_edge_prob_points: number; neutral: boolean;
    favorite: "home" | "away" | null;
  };
  model: { name: string; home_bump: number; k_regular: number; mov: boolean; live: string };
  calibration_context: {
    lo: number; hi: number; n: number; mean_predicted: number; home_win_rate: number; source: string;
  } | null;
  home: DetailSide;
  away: DetailSide;
  head_to_head: { date: string; season: string | null; home: string; away: string; home_score: number; away_score: number }[];
  live_history: { t: string; period: number; time_remaining_s: number; home_score: number; away_score: number; home_wp: number }[];
  pitching?: { home: PitcherSide; away: PitcherSide };
  attribution?: string;
  projections: GameProjections | null;
  wp_curve?: WPCurve | null;
};

export type WPPoint = { x: number; wp: number; label: string; text: string | null };
export type WPCurve = { points: WPPoint[]; swings: { x: number; from: number; to: number; label: string; text: string }[] };

export type SkaterProjection = {
  player_id: number; name: string; pos: "F" | "D"; headshot?: string | null;
  p_point: number; p_goal: number;
};

export type GameProjections = { home: SkaterProjection[]; away: SkaterProjection[]; note: string; model: string };

export type ScorerRow = SkaterProjection & { team: string; opponent: string; is_home: boolean; game_id: number };

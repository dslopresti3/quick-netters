export type ConfidenceTag = "high" | "medium" | "watch";

export type DateAvailabilityStatus = "invalid_date" | "no_schedule" | "missing_projections" | "missing_odds" | "ready";

export interface DateAvailabilityResponse {
  selected_date: string;
  min_allowed_date: string;
  max_allowed_date: string;
  valid_by_product_rule: boolean;
  schedule_available: boolean;
  projections_available: boolean;
  odds_available: boolean;
  status: DateAvailabilityStatus;
  messages: string[];
}

export interface TeamProjectionLeader {
  team: string;
  player_id: string;
  player_name: string;
  player_team?: string;
  team_name?: string;
  model_probability: number;
}

export interface GameSummary {
  game_id: string;
  game_time: string;
  display_game_time?: string;
  display_timezone?: string;
  away_team: string;
  home_team: string;
  away_top_projected_scorer?: TeamProjectionLeader;
  home_top_projected_scorer?: TeamProjectionLeader;
}

export interface Recommendation {
  game_id: string;
  game_time: string;
  away_team: string;
  home_team: string;
  player_id: string;
  player_name: string;
  player_team?: string;
  team_name?: string;
  model_probability: number;
  implied_probability?: number;
  fair_odds: number;
  market_odds: number;
  decimal_odds?: number;
  edge: number;
  ev: number;
  odds_snapshot_at?: string;
  confidence_tag?: ConfidenceTag;
  goals_this_year?: number;
  first_goals_this_year?: number;
}

export interface GamesResponse {
  date: string;
  games: GameSummary[];
  projections_available: boolean;
  odds_available: boolean;
  notes: string[];
}

export interface DailyRecommendationsResponse {
  date: string;
  recommendations: Recommendation[];
  projections_available: boolean;
  odds_available: boolean;
  notes: string[];
}

export interface GameRecommendationsResponse {
  date: string;
  game: GameSummary;
  recommendations: Recommendation[];
  top_plays: Recommendation[];
  best_bet?: Recommendation;
  underdog_value_play?: Recommendation;
  projections_available: boolean;
  odds_available: boolean;
  notes: string[];
}


export interface HistoricalGameSnapshot {
  game: GameSummary;
  top_plays: Recommendation[];
  best_bet?: Recommendation;
  underdog_value_play?: Recommendation;
}

export interface LockedRecommendationSnapshot {
  date: string;
  market: "first_goal" | "anytime";
  snapshot_created_at: string;
  earliest_game_time_et: string;
  lock_cutoff_et: string;
  top_overall: Recommendation[];
  games: HistoricalGameSnapshot[];
}

export interface RecommendationHistoryResponse {
  date?: string;
  market?: "first_goal" | "anytime";
  is_locked?: boolean;
  earliest_game_time_et?: string;
  lock_cutoff_et?: string;
  snapshots: LockedRecommendationSnapshot[];
}

export interface HistoricalDateAvailabilityResponse {
  selected_date?: string;
  market?: "first_goal" | "anytime";
  available_dates: string[];
  min_available_date?: string;
  max_available_date?: string;
  has_snapshot: boolean;
}

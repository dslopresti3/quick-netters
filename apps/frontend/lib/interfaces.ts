export type ConfidenceTag = "high" | "medium" | "watch";

export interface TeamProjectionLeader {
  team: string;
  player_id: string;
  player_name: string;
  model_probability: number;
}

export interface GameSummary {
  game_id: string;
  game_time: string;
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
  model_probability: number;
  implied_probability?: number;
  fair_odds: number;
  market_odds: number;
  edge: number;
  ev: number;
  odds_snapshot_at?: string;
  confidence_tag?: ConfidenceTag;
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
  projections_available: boolean;
  odds_available: boolean;
  notes: string[];
}

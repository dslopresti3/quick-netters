export type ConfidenceTag = "high" | "medium" | "watch";

export interface GameSummary {
  game_id: string;
  game_time: string;
  away_team: string;
  home_team: string;
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
}

export interface DailyRecommendationsResponse {
  date: string;
  recommendations: Recommendation[];
}

export interface GameRecommendationsResponse {
  date: string;
  game: GameSummary;
  recommendations: Recommendation[];
}

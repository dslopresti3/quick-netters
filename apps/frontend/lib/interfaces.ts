export interface ScheduleMatch {
  id: string;
  tournament: string;
  playerA: string;
  playerB: string;
  startTimeUtc: string;
}

export interface PlayerProjection {
  player: string;
  holdPct: number;
  breakPct: number;
  fitnessScore: number;
}

export interface MatchOdds {
  matchId: string;
  sportsbook: string;
  playerA: number;
  playerB: number;
}

export interface Recommendation {
  matchId: string;
  confidence: number;
  rationale: string;
}

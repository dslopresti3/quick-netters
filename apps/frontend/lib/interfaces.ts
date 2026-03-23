export interface TeamFirstGoalProjection {
  team: string;
  topScorer: string;
  fairProbability: number;
}

export interface GameSlateCard {
  id: string;
  date: string;
  league: string;
  startTimeUtc: string;
  awayTeam: TeamFirstGoalProjection;
  homeTeam: TeamFirstGoalProjection;
  marketOdds: string;
  edge: string;
}

export interface ValuePick {
  gameId: string;
  player: string;
  team: string;
  modelProbability: number;
  fairOdds: string;
  marketOdds: string;
  edge: string;
}

export interface PlayerBet extends ValuePick {
  confidenceTier: "high" | "medium" | "watch";
}

export interface GameDetail {
  gameId: string;
  date: string;
  matchup: string;
  startTimeUtc: string;
  topBets: PlayerBet[];
  candidatePlayers: PlayerBet[];
}

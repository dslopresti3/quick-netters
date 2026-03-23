import type { MatchOdds, PlayerProjection, Recommendation, ScheduleMatch } from "./interfaces";

export const mockSchedule: ScheduleMatch[] = [
  {
    id: "m-001",
    tournament: "Mock Open",
    playerA: "Iga S.",
    playerB: "Aryna S.",
    startTimeUtc: "2026-03-24T14:00:00Z",
  },
  {
    id: "m-002",
    tournament: "Mock Open",
    playerA: "Carlos A.",
    playerB: "Jannik S.",
    startTimeUtc: "2026-03-24T18:00:00Z",
  },
];

export const mockProjections: PlayerProjection[] = [
  { player: "Iga S.", holdPct: 72, breakPct: 44, fitnessScore: 91 },
  { player: "Aryna S.", holdPct: 78, breakPct: 36, fitnessScore: 87 },
  { player: "Carlos A.", holdPct: 83, breakPct: 32, fitnessScore: 90 },
  { player: "Jannik S.", holdPct: 84, breakPct: 31, fitnessScore: 89 },
];

export const mockOdds: MatchOdds[] = [
  { matchId: "m-001", sportsbook: "MockBook", playerA: -130, playerB: +115 },
  { matchId: "m-002", sportsbook: "MockBook", playerA: -110, playerB: -105 },
];

export const mockRecommendations: Recommendation[] = [
  { matchId: "m-001", confidence: 0.63, rationale: "Higher break conversion under similar pace conditions." },
  { matchId: "m-002", confidence: 0.54, rationale: "Tight edge from serve+return blended model." },
];

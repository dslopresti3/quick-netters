import type { GameDetail, GameSlateCard, PlayerBet, ValuePick } from "./interfaces";

const formatDate = (date: Date): string => date.toISOString().slice(0, 10);

const today = new Date();
const tomorrow = new Date(today);
tomorrow.setDate(today.getDate() + 1);

export const ALLOWED_DATES = {
  today: formatDate(today),
  tomorrow: formatDate(tomorrow),
};

const baseGames: Omit<GameSlateCard, "date">[] = [
  {
    id: "g-nyr-vs-bos",
    league: "NHL",
    startTimeUtc: "2026-03-23T23:00:00Z",
    awayTeam: { team: "NY Rangers", topScorer: "Chris Kreider", fairProbability: 0.19 },
    homeTeam: { team: "Boston Bruins", topScorer: "David Pastrnak", fairProbability: 0.23 },
    marketOdds: "Placeholder (-105 / +115)",
    edge: "Placeholder (+2.1%)",
  },
  {
    id: "g-col-vs-dal",
    league: "NHL",
    startTimeUtc: "2026-03-24T00:30:00Z",
    awayTeam: { team: "Colorado Avalanche", topScorer: "Nathan MacKinnon", fairProbability: 0.24 },
    homeTeam: { team: "Dallas Stars", topScorer: "Roope Hintz", fairProbability: 0.16 },
    marketOdds: "Placeholder (+180 / +260)",
    edge: "Placeholder (+1.4%)",
  },
  {
    id: "g-lak-vs-vgk",
    league: "NHL",
    startTimeUtc: "2026-03-24T03:00:00Z",
    awayTeam: { team: "LA Kings", topScorer: "Kevin Fiala", fairProbability: 0.17 },
    homeTeam: { team: "Vegas Golden Knights", topScorer: "Jack Eichel", fairProbability: 0.21 },
    marketOdds: "Placeholder (+320 / +210)",
    edge: "Placeholder (+0.8%)",
  },
];

const baseTopPicks: Omit<ValuePick, "gameId">[] = [
  {
    player: "Nathan MacKinnon",
    team: "Colorado Avalanche",
    modelProbability: 0.24,
    fairOdds: "+317",
    marketOdds: "Placeholder (+350)",
    edge: "Placeholder (+2.7%)",
  },
  {
    player: "David Pastrnak",
    team: "Boston Bruins",
    modelProbability: 0.23,
    fairOdds: "+335",
    marketOdds: "Placeholder (+360)",
    edge: "Placeholder (+1.9%)",
  },
  {
    player: "Jack Eichel",
    team: "Vegas Golden Knights",
    modelProbability: 0.21,
    fairOdds: "+376",
    marketOdds: "Placeholder (+410)",
    edge: "Placeholder (+1.4%)",
  },
];

const detailPlayersByGame: Record<string, Omit<PlayerBet, "gameId">[]> = {
  "g-nyr-vs-bos": [
    { player: "David Pastrnak", team: "Boston Bruins", modelProbability: 0.23, fairOdds: "+335", marketOdds: "Placeholder (+360)", edge: "Placeholder (+1.9%)", confidenceTier: "high" },
    { player: "Chris Kreider", team: "NY Rangers", modelProbability: 0.19, fairOdds: "+426", marketOdds: "Placeholder (+470)", edge: "Placeholder (+1.2%)", confidenceTier: "high" },
    { player: "Artemi Panarin", team: "NY Rangers", modelProbability: 0.14, fairOdds: "+614", marketOdds: "Placeholder (+680)", edge: "Placeholder (+0.9%)", confidenceTier: "medium" },
    { player: "Brad Marchand", team: "Boston Bruins", modelProbability: 0.13, fairOdds: "+669", marketOdds: "Placeholder (+640)", edge: "Placeholder (-0.4%)", confidenceTier: "watch" },
    { player: "Charlie Coyle", team: "Boston Bruins", modelProbability: 0.08, fairOdds: "+1150", marketOdds: "Placeholder (+1250)", edge: "Placeholder (+0.6%)", confidenceTier: "watch" },
  ],
  "g-col-vs-dal": [
    { player: "Nathan MacKinnon", team: "Colorado Avalanche", modelProbability: 0.24, fairOdds: "+317", marketOdds: "Placeholder (+350)", edge: "Placeholder (+2.7%)", confidenceTier: "high" },
    { player: "Roope Hintz", team: "Dallas Stars", modelProbability: 0.16, fairOdds: "+525", marketOdds: "Placeholder (+560)", edge: "Placeholder (+0.8%)", confidenceTier: "high" },
    { player: "Mikko Rantanen", team: "Colorado Avalanche", modelProbability: 0.15, fairOdds: "+567", marketOdds: "Placeholder (+600)", edge: "Placeholder (+0.7%)", confidenceTier: "medium" },
    { player: "Jason Robertson", team: "Dallas Stars", modelProbability: 0.14, fairOdds: "+614", marketOdds: "Placeholder (+610)", edge: "Placeholder (-0.1%)", confidenceTier: "watch" },
    { player: "Jamie Benn", team: "Dallas Stars", modelProbability: 0.09, fairOdds: "+1011", marketOdds: "Placeholder (+1200)", edge: "Placeholder (+1.1%)", confidenceTier: "watch" },
  ],
  "g-lak-vs-vgk": [
    { player: "Jack Eichel", team: "Vegas Golden Knights", modelProbability: 0.21, fairOdds: "+376", marketOdds: "Placeholder (+410)", edge: "Placeholder (+1.4%)", confidenceTier: "high" },
    { player: "Kevin Fiala", team: "LA Kings", modelProbability: 0.17, fairOdds: "+488", marketOdds: "Placeholder (+510)", edge: "Placeholder (+0.6%)", confidenceTier: "high" },
    { player: "Adrian Kempe", team: "LA Kings", modelProbability: 0.14, fairOdds: "+614", marketOdds: "Placeholder (+640)", edge: "Placeholder (+0.4%)", confidenceTier: "medium" },
    { player: "Mark Stone", team: "Vegas Golden Knights", modelProbability: 0.11, fairOdds: "+809", marketOdds: "Placeholder (+760)", edge: "Placeholder (-0.3%)", confidenceTier: "watch" },
    { player: "Trevor Moore", team: "LA Kings", modelProbability: 0.09, fairOdds: "+1011", marketOdds: "Placeholder (+1050)", edge: "Placeholder (+0.2%)", confidenceTier: "watch" },
  ],
};

export const mockSlateByDate: Record<string, GameSlateCard[]> = {
  [ALLOWED_DATES.today]: baseGames.map((game) => ({ ...game, date: ALLOWED_DATES.today })),
  [ALLOWED_DATES.tomorrow]: [],
};

export const mockTopPicksByDate: Record<string, ValuePick[]> = {
  [ALLOWED_DATES.today]: baseTopPicks.map((pick, index) => ({ ...pick, gameId: baseGames[index].id })),
  [ALLOWED_DATES.tomorrow]: [],
};

export const mockDetailsByGameAndDate: Record<string, Record<string, GameDetail>> = {
  [ALLOWED_DATES.today]: {
    "g-nyr-vs-bos": {
      gameId: "g-nyr-vs-bos",
      date: ALLOWED_DATES.today,
      matchup: "NY Rangers @ Boston Bruins",
      startTimeUtc: "2026-03-23T23:00:00Z",
      topBets: detailPlayersByGame["g-nyr-vs-bos"].slice(0, 3).map((player) => ({ ...player, gameId: "g-nyr-vs-bos" })),
      candidatePlayers: detailPlayersByGame["g-nyr-vs-bos"].slice(3).map((player) => ({ ...player, gameId: "g-nyr-vs-bos" })),
    },
    "g-col-vs-dal": {
      gameId: "g-col-vs-dal",
      date: ALLOWED_DATES.today,
      matchup: "Colorado Avalanche @ Dallas Stars",
      startTimeUtc: "2026-03-24T00:30:00Z",
      topBets: detailPlayersByGame["g-col-vs-dal"].slice(0, 3).map((player) => ({ ...player, gameId: "g-col-vs-dal" })),
      candidatePlayers: detailPlayersByGame["g-col-vs-dal"].slice(3).map((player) => ({ ...player, gameId: "g-col-vs-dal" })),
    },
    "g-lak-vs-vgk": {
      gameId: "g-lak-vs-vgk",
      date: ALLOWED_DATES.today,
      matchup: "LA Kings @ Vegas Golden Knights",
      startTimeUtc: "2026-03-24T03:00:00Z",
      topBets: detailPlayersByGame["g-lak-vs-vgk"].slice(0, 3).map((player) => ({ ...player, gameId: "g-lak-vs-vgk" })),
      candidatePlayers: detailPlayersByGame["g-lak-vs-vgk"].slice(3).map((player) => ({ ...player, gameId: "g-lak-vs-vgk" })),
    },
  },
  [ALLOWED_DATES.tomorrow]: {},
};

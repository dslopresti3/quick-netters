export type RecommendationMarket = "first_goal" | "anytime";

export const DEFAULT_MARKET: RecommendationMarket = "first_goal";

const MARKET_DISPLAY_LABELS: Record<RecommendationMarket, string> = {
  first_goal: "First Goal",
  anytime: "Anytime",
};

export function resolveMarket(rawMarket?: string): RecommendationMarket {
  return rawMarket === "anytime" ? "anytime" : DEFAULT_MARKET;
}

export function marketLabel(market: RecommendationMarket): string {
  return MARKET_DISPLAY_LABELS[market];
}

export function marketDescriptor(market: RecommendationMarket): string {
  return `${marketLabel(market)} market`;
}

export function marketScoreVerb(market: RecommendationMarket): string {
  return market === "anytime" ? "scores a goal" : "scores the first goal";
}

export type SeasonProductionLabels = {
  left: string;
  right: string;
};

export function marketSeasonProductionLabels(market: RecommendationMarket): SeasonProductionLabels {
  if (market === "anytime") {
    return {
      left: "Goals scored",
      right: "First goals scored",
    };
  }

  return {
    left: "Goals this year",
    right: "First goals this year",
  };
}

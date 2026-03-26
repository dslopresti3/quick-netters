export type RecommendationMarket = "first_goal" | "anytime";

export const DEFAULT_MARKET: RecommendationMarket = "first_goal";

export function resolveMarket(rawMarket?: string): RecommendationMarket {
  return rawMarket === "anytime" ? "anytime" : DEFAULT_MARKET;
}

export function marketLabel(market: RecommendationMarket): string {
  return market === "anytime" ? "Anytime Goal Scorer" : "First Goal Scorer";
}

import Link from "next/link";
import type { RecommendationMarket } from "../lib/market";
import { marketLabel } from "../lib/market";

type MarketToggleProps = {
  selectedDate: string;
  displayTimezone: string;
  selectedMarket: RecommendationMarket;
  path: string;
};

const OPTIONS: RecommendationMarket[] = ["first_goal", "anytime"];

export function MarketToggle({ selectedDate, displayTimezone, selectedMarket, path }: MarketToggleProps) {
  return (
    <nav className="market-toggle" aria-label="Goal scorer market">
      {OPTIONS.map((option) => {
        const href = `${path}?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}&market=${option}`;
        const active = option === selectedMarket;
        return (
          <Link key={option} href={href} className={`market-toggle-option${active ? " is-active" : ""}`} aria-current={active ? "page" : undefined}>
            {marketLabel(option)}
          </Link>
        );
      })}
    </nav>
  );
}

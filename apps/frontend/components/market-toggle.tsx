import Link from "next/link";
import type { RecommendationMarket } from "../lib/market";

type MarketToggleProps = {
  selectedDate: string;
  displayTimezone: string;
  selectedMarket: RecommendationMarket;
  path: string;
};

const OPTIONS: Array<{ value: RecommendationMarket; label: string }> = [
  { value: "first_goal", label: "First Goal" },
  { value: "anytime", label: "Anytime" },
];

export function MarketToggle({ selectedDate, displayTimezone, selectedMarket, path }: MarketToggleProps) {
  return (
    <nav className="market-toggle" aria-label="Goal scorer market">
      {OPTIONS.map((option) => {
        const href = `${path}?date=${selectedDate}&timezone=${encodeURIComponent(displayTimezone)}&market=${option.value}`;
        const active = option.value === selectedMarket;
        return (
          <Link key={option.value} href={href} className={`market-toggle-option${active ? " is-active" : ""}`} aria-current={active ? "page" : undefined}>
            {option.label}
          </Link>
        );
      })}
    </nav>
  );
}

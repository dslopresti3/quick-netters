import Link from "next/link";
import { ReactNode } from "react";
import { MarketToggle } from "./market-toggle";
import type { RecommendationMarket } from "../lib/market";

type AppShellHeaderProps = {
  activeNav: "home" | "slate" | "history";
  selectedDate?: string;
  displayTimezone?: string;
  selectedMarket?: RecommendationMarket;
  marketPath?: string;
  utilityLinks?: Array<{ href: string; label: string }>;
  children?: ReactNode;
};

function resolveNavHref(path: "/" | "/slate" | "/history", selectedDate?: string, displayTimezone?: string, selectedMarket?: RecommendationMarket) {
  if (!selectedDate || !displayTimezone || !selectedMarket || path === "/") {
    return path;
  }

  return `${path}?date=${encodeURIComponent(selectedDate)}&timezone=${encodeURIComponent(displayTimezone)}&market=${selectedMarket}`;
}

export function AppShellHeader({
  activeNav,
  selectedDate,
  displayTimezone,
  selectedMarket,
  marketPath,
  utilityLinks,
  children,
}: AppShellHeaderProps) {
  const navItems = [
    { key: "home", label: "Home", href: resolveNavHref("/", selectedDate, displayTimezone, selectedMarket) },
    { key: "slate", label: "Daily Slate", href: resolveNavHref("/slate", selectedDate, displayTimezone, selectedMarket) },
    { key: "history", label: "History", href: resolveNavHref("/history", selectedDate, displayTimezone, selectedMarket) },
  ] as const;

  return (
    <header className="app-shell-header stack-gap-sm">
      <div className="app-shell-bar">
        <div className="app-branding">
          <p className="app-kicker">Sports Analytics Suite</p>
          <Link href="/" className="app-brand-link">Quick Netters</Link>
        </div>

        <nav className="app-nav" aria-label="Primary">
          {navItems.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              className={`app-nav-link${item.key === activeNav ? " is-active" : ""}`}
              aria-current={item.key === activeNav ? "page" : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="app-shell-controls">
          {marketPath && selectedDate && displayTimezone && selectedMarket && (
            <MarketToggle
              selectedDate={selectedDate}
              displayTimezone={displayTimezone}
              selectedMarket={selectedMarket}
              path={marketPath}
            />
          )}
          {selectedDate && <span className="context-chip">Date · {selectedDate}</span>}
          {utilityLinks?.map((link) => (
            <Link key={link.href} href={link.href} className="utility-link">
              {link.label}
            </Link>
          ))}
        </div>
      </div>
      {children}
    </header>
  );
}

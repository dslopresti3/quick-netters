import { ReactNode } from "react";
import type { RecommendationMarket } from "../lib/market";

type PageHeaderProps = {
  title: string;
  description: string;
  contextChips?: string[];
  market?: RecommendationMarket;
  children?: ReactNode;
};

export function PageHeader({ title, description, contextChips, market, children }: PageHeaderProps) {
  return (
    <section className={`page-hero stack-gap-sm${market ? ` page-hero-${market}` : ""}`}>
      <div className="stack-gap-sm">
        <h1>{title}</h1>
        <p className="subtitle">{description}</p>
      </div>
      {contextChips && contextChips.length > 0 && (
        <div className="hero-chip-row">
          {contextChips.map((chip) => (
            <span key={chip} className="hero-chip">{chip}</span>
          ))}
        </div>
      )}
      {children}
    </section>
  );
}

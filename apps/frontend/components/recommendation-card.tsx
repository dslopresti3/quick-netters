import type { Recommendation } from "../lib/interfaces";
import type { RecommendationMarket } from "../lib/market";
import { marketLabel, marketScoreVerb, marketSeasonProductionLabels } from "../lib/market";

type RecommendationCardProps = {
  recommendation: Recommendation;
  rank?: number;
  market?: RecommendationMarket;
  variant?: "top_play" | "best_bet" | "underdog_value";
};

type MetricLabelProps = {
  label: string;
  tooltip: string;
};

function formatSignedOdds(value: number): string {
  return value > 0 ? `+${value}` : `${value}`;
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function MetricLabel({ label, tooltip }: MetricLabelProps) {
  return (
    <span className="metric-label metric-label-with-help">
      {label}
      <span className="metric-help-icon" role="img" aria-label={`${label} info`} title={tooltip}>
        ⓘ
      </span>
    </span>
  );
}

export function RecommendationCard({ recommendation, rank, market = "first_goal", variant = "top_play" }: RecommendationCardProps) {
  const marketName = marketLabel(market);
  const marketChipClassName = `market-chip market-chip-${market}`;
  const variantClassName = `recommendation-card-${variant}`;
  const seasonProductionLabels = marketSeasonProductionLabels(market);
  const seasonProductionValues = {
    left: recommendation.goals_this_year ?? "-",
    right: recommendation.first_goals_this_year ?? "-",
  };

  return (
    <article className={`recommendation-card ${variantClassName} stack-gap-sm`}>
      <header className="recommendation-card-header">
        <div className="recommendation-card-title-group">
          {typeof rank === "number" && <p className="recommendation-rank">Top {rank}</p>}
          <h3 className="recommendation-player-name">{recommendation.player_name}</h3>
          <p className="helper-text">{recommendation.player_team ?? recommendation.team_name ?? `${recommendation.away_team} / ${recommendation.home_team}`}</p>
        </div>
        <div className="recommendation-card-meta">
          <span className={`recommendation-variant-tag recommendation-variant-tag-${variant}`}>
            {variant === "best_bet" ? "Best Bet" : variant === "underdog_value" ? "Underdog Value" : "Top Play"}
          </span>
          <span className={marketChipClassName}>{marketName}</span>
          {recommendation.confidence_tag && (
            <span className={`confidence-badge confidence-${recommendation.confidence_tag}`}>{recommendation.confidence_tag}</span>
          )}
        </div>
      </header>

      <section className="metrics-section">
        <p className="metrics-heading">Primary betting metrics</p>
        <div className="primary-metrics-grid">
          <div className="primary-metric primary-metric-signal">
            <MetricLabel
              label="Model probability"
              tooltip={`Your model's estimated chance this player ${marketScoreVerb(market)}. Higher values indicate a stronger model signal.`}
            />
            <strong className="metric-value-prominent">{formatPercent(recommendation.model_probability)}</strong>
          </div>
          <div className="primary-metric">
            <MetricLabel
              label="Market odds"
              tooltip="The sportsbook's current price for this pick. Used to derive implied probability and EV."
            />
            <strong className="metric-value">{formatSignedOdds(recommendation.market_odds)}</strong>
            <span className="metric-secondary-text">
              Implied: {recommendation.implied_probability !== undefined ? formatPercent(recommendation.implied_probability) : "-"}
            </span>
          </div>
          <div className="primary-metric">
            <MetricLabel
              label="Fair odds"
              tooltip="Odds implied by the model probability. Compare this to market odds to spot potential value."
            />
            <strong className="metric-value">{formatSignedOdds(recommendation.fair_odds)}</strong>
          </div>
        </div>
      </section>

      <section className="metrics-section">
        <p className="metrics-heading">Value metrics</p>
        <div className="value-chip-row">
          <div className="metric-chip metric-chip-value metric-chip-primary">
            <MetricLabel
              label="Edge"
              tooltip="Difference between model probability and implied probability. Positive edge suggests potential value."
            />
            <strong>{formatPercent(recommendation.edge)}</strong>
          </div>
          <div className="metric-chip metric-chip-value">
            <MetricLabel
              label="EV"
              tooltip="Expected value per unit stake from model probability and market payout. Positive EV indicates a profitable bet over time."
            />
            <strong>{formatPercent(recommendation.ev)}</strong>
          </div>
        </div>
      </section>

      <section className="metrics-section metrics-section-season-production">
        <p className="metrics-heading">Season production</p>
        <div className="supporting-metrics-grid">
          <div className="supporting-metric">
            <span className="metric-label">{seasonProductionLabels.left}</span>
            <strong>{seasonProductionValues.left}</strong>
          </div>
          <div className="supporting-metric">
            <span className="metric-label">{seasonProductionLabels.right}</span>
            <strong>{seasonProductionValues.right}</strong>
          </div>
        </div>
      </section>
    </article>
  );
}

import type { Recommendation } from "../lib/interfaces";

type RecommendationCardProps = {
  recommendation: Recommendation;
  rank?: number;
};

function formatSignedOdds(value: number): string {
  return value > 0 ? `+${value}` : `${value}`;
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function RecommendationCard({ recommendation, rank }: RecommendationCardProps) {
  return (
    <article className="recommendation-card stack-gap-sm">
      <header className="recommendation-card-header">
        <div>
          {typeof rank === "number" && <p className="recommendation-rank">#{rank}</p>}
          <h3 className="recommendation-player-name">{recommendation.player_name}</h3>
        </div>
        {recommendation.confidence_tag && (
          <span className={`confidence-badge confidence-${recommendation.confidence_tag}`}>{recommendation.confidence_tag}</span>
        )}
      </header>

      <section className="metrics-section">
        <p className="metrics-heading">Primary betting metrics</p>
        <div className="primary-metrics-grid">
          <div className="primary-metric">
            <span className="metric-label">Model probability</span>
            <strong className="metric-value-prominent">{formatPercent(recommendation.model_probability)}</strong>
          </div>
          <div className="primary-metric">
            <span className="metric-label">Fair odds</span>
            <strong className="metric-value-prominent">{formatSignedOdds(recommendation.fair_odds)}</strong>
          </div>
          <div className="primary-metric">
            <span className="metric-label">Market odds</span>
            <strong className="metric-value-prominent">{formatSignedOdds(recommendation.market_odds)}</strong>
          </div>
        </div>
      </section>

      <section className="metrics-section">
        <p className="metrics-heading">Value metrics</p>
        <div className="value-chip-row">
          <div className="metric-chip metric-chip-value">
            <span className="metric-label">Edge</span>
            <strong>{formatPercent(recommendation.edge)}</strong>
          </div>
          <div className="metric-chip metric-chip-value">
            <span className="metric-label">EV</span>
            <strong>{formatPercent(recommendation.ev)}</strong>
          </div>
        </div>
      </section>

      <section className="metrics-section">
        <p className="metrics-heading">Season production</p>
        <div className="supporting-metrics-grid">
          <div className="supporting-metric">
            <span className="metric-label">Goals this year</span>
            <strong>{recommendation.goals_this_year ?? "-"}</strong>
          </div>
          <div className="supporting-metric">
            <span className="metric-label">First goals this year</span>
            <strong>{recommendation.first_goals_this_year ?? "-"}</strong>
          </div>
        </div>
      </section>
    </article>
  );
}

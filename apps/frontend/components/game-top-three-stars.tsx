"use client";

import type { Recommendation } from "../lib/interfaces";

type GameTopThreeStarsProps = {
  picks: Recommendation[];
};

const STAR_LABELS = ["#1 Star", "#2 Star", "#3 Star"];

function formatSignedOdds(value: number): string {
  return value > 0 ? `+${value}` : `${value}`;
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function buildHeadshotUrl(playerId: string): string | null {
  if (!/^\d+$/.test(playerId)) {
    return null;
  }
  return `https://assets.nhle.com/mugs/nhl/latest/168x168/${playerId}.png`;
}

function PlayerHeadshot({ playerId, playerName }: { playerId: string; playerName: string }) {
  const url = buildHeadshotUrl(playerId);
  const initials = playerName
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((token) => token[0]?.toUpperCase() ?? "")
    .join("");

  if (!url) {
    return <div className="headshot-placeholder" aria-label={`${playerName} avatar placeholder`}>{initials || "P"}</div>;
  }

  return (
    <img
      src={url}
      alt={playerName}
      className="player-headshot"
      loading="lazy"
      onError={(event) => {
        event.currentTarget.style.display = "none";
        const fallback = event.currentTarget.nextElementSibling as HTMLDivElement | null;
        if (fallback) fallback.style.display = "grid";
      }}
    />
  );
}

export function GameTopThreeStars({ picks }: GameTopThreeStarsProps) {
  return (
    <div className="stars-grid">
      {picks.map((pick, index) => (
        <article key={pick.player_id} className="star-card stack-gap-sm">
          <header className="star-card-header">
            <span className="star-rank">{STAR_LABELS[index] ?? `#${index + 1}`}</span>
            {pick.confidence_tag && <span className={`confidence-badge confidence-${pick.confidence_tag}`}>{pick.confidence_tag}</span>}
          </header>

          <div className="star-player-row">
            <div className="headshot-wrap">
              <PlayerHeadshot playerId={pick.player_id} playerName={pick.player_name} />
              <div className="headshot-placeholder" style={{ display: "none" }} aria-hidden="true">
                {pick.player_name.slice(0, 1).toUpperCase()}
              </div>
            </div>
            <div>
              <h3 className="recommendation-player-name">{pick.player_name}</h3>
              <p className="helper-text star-team-label">{pick.player_team ?? `${pick.away_team} / ${pick.home_team}`}</p>
            </div>
          </div>

          <div className="star-primary-metrics">
            <div>
              <span className="metric-label">Model probability</span>
              <strong className="metric-value-prominent">{formatPercent(pick.model_probability)}</strong>
            </div>
            <div>
              <span className="metric-label">Market odds</span>
              <strong className="metric-value-prominent">{formatSignedOdds(pick.market_odds)}</strong>
            </div>
          </div>

          <div className="star-secondary-row">
            <div className="metric-chip metric-chip-value">
              <span className="metric-label">EV</span>
              <strong>{formatPercent(pick.ev)}</strong>
            </div>
            <div className="supporting-metric">
              <span className="metric-label">Goals this year</span>
              <strong>{pick.goals_this_year ?? "-"}</strong>
            </div>
            <div className="supporting-metric">
              <span className="metric-label">First goals this year</span>
              <strong>{pick.first_goals_this_year ?? "-"}</strong>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}
